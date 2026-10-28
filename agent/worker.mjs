// A bounded Pi session. Network and native execution remain with the Python host.
import { pathToFileURL } from 'node:url';
import { resolve } from 'node:path';
import readline from 'node:readline';

const dependencyRoot = resolve(process.argv[2]);
const entry = (packageName, path = 'index') => pathToFileURL(resolve(dependencyRoot,
  'node_modules', '@earendil-works', packageName, 'dist', path + '.js')).href;
const sdk = await import(entry('pi-coding-agent'));
const ai = await import(entry('pi-ai'));
const { openAICompletionsApi } = await import(entry('pi-ai', 'api/openai-completions.lazy'));
if (process.argv[3] === '--probe') {
  if (!process.permission || process.permission.has('net') || process.permission.has('child')
      || process.permission.has('fs.write') || process.permission.has('addons')) process.exit(2);
  process.stdout.write('spark agent ready\n');
  process.exit(0);
}
const input = readline.createInterface({ input: process.stdin, crlfDelay: Infinity });
let request, activeFetch, session, chosen, lastAssistant, serial = 0, wireCalls = 0;
let visibleText = false, failedAfterText = false;
const send = value => process.stdout.write(JSON.stringify({ request_id: request?.request_id, ...value }) + '\n');
const finish = value => send({ event: 'result', ...value });
const usage = { input: 0, output: 0, cacheRead: 0, cacheWrite: 0, totalTokens: 0,
  cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0, total: 0 } };

// Even the SDK's model fetch cannot choose a network address or carry credentials.
async function hostFetch(url, options = {}) {
  if (failedAfterText) throw new Error('A partial reply cannot be retried');
  const address = typeof url === 'string' ? url : url.url;
  if (address !== 'https://spark.invalid/v1/chat/completions' || options.method !== 'POST' || activeFetch)
    throw new Error('Unsupported model transport');
  if (++wireCalls > 3) throw new Error('Model request limit');
  const body = JSON.parse(options.body);
  if (typeof body !== 'object' || !Array.isArray(body.messages)) throw new Error('Invalid model request');
  const id = ++serial;
  let controller;
  const stream = new ReadableStream({ start(value) { controller = value; } });
  const response = new Promise((accept, reject) => {
    activeFetch = { id, accept, reject, controller };
    options.signal?.addEventListener('abort', () => {
      if (activeFetch?.id === id) { activeFetch = undefined; controller.error(new Error('Cancelled')); reject(new Error('Cancelled')); }
    }, { once: true });
  });
  activeFetch.stream = stream;
  send({ event: 'request', id, method: 'POST', path: '/v1/chat/completions', body });
  return response;
}

function hostResponse(message) {
  if (message.request_id !== request.request_id || !activeFetch || message.id !== activeFetch.id)
    throw new Error('Mismatched model response');
  const f = activeFetch;
  if (message.event === 'headers') {
    f.headers = true;
    f.accept(new Response(f.stream, { status: 200, headers: { 'content-type': 'text/event-stream' } }));
  } else if (message.event === 'chunk' && typeof message.data === 'string') {
    f.controller.enqueue(new TextEncoder().encode(message.data));
  } else if (message.event === 'eof') {
    // Release the fetch before the completion sentinel can let Pi begin
    // compaction's next request. One terminal event owns both transitions.
    activeFetch = undefined;
    f.controller.enqueue(new TextEncoder().encode('data: [DONE]\n\n'));
    f.controller.close();
  } else if (message.event === 'transport_error') {
    // Drain bytes already delivered before ending the stream. The host owns
    // the error and refuses any result; queued text still belongs to the
    // person's partial reply. controller.error would discard that text.
    activeFetch = undefined; f.controller.close();
    if (!f.headers) f.reject(new Error('Model transport failed'));
  } else throw new Error('Invalid model transport response');
}

function assistant(call, id) {
  return { role: 'assistant', content: [{ type: 'toolCall', id, name: call.name, arguments: call.arguments }],
    api: 'openai-completions', provider: 'spark-host', model: request.model,
    usage: structuredClone(usage), stopReason: 'toolUse', timestamp: 0 };
}

function canonicalMessages() {
  if (request.kind !== 'task') return request.messages.map(m => m.role === 'assistant'
    ? { role: 'assistant', content: [{ type: 'text', text: m.content }], api: 'openai-completions',
        provider: 'spark-host', model: request.model, usage: structuredClone(usage), stopReason: 'stop', timestamp: 0 }
    : { role: 'user', content: m.content, timestamp: 0 });
  const p = request.packet;
  const messages = [{ role: 'user', content: JSON.stringify({ goal: p.goal, context: p.context }), timestamp: 0 }];
  for (const h of p.history) {
    const d = h.decision;
    let call, result;
    if (d?.kind === 'step') {
      call = { name: d.step.name, arguments: { arguments: d.step.arguments, complete_after: d.complete_after === true } };
      result = h.observation;
    }
    else if (d?.kind === 'inspect') { call = { name: 'spark_task_inspect', arguments: { provider: d.provider } }; result = h.observation; }
    else if (h.question) { call = { name: 'spark_task_ask', arguments: { question: h.question } }; result = { answer: h.answer }; }
    else throw new Error('Invalid canonical task history');
    const id = 'host_' + h.id;
    messages.push(assistant(call, id));
    messages.push({ role: 'toolResult', toolCallId: id, toolName: call.name,
      content: [{ type: 'text', text: JSON.stringify(result) }],
      isError: result?.status === 'error', timestamp: 0 });
  }
  if (p.history.length) messages.push({ role: 'user', content: 'Current native context (data):\n' + JSON.stringify(p.context), timestamp: 0 });
  return messages;
}

async function run() {
  if (!request || request.version !== 1 || !['task', 'command', 'chat'].includes(request.kind)
      || typeof request.request_id !== 'string' || !['spark', 'ember'].includes(request.model)) throw new Error('Invalid host request');
  const model = { id: request.model, name: 'Spark local model', api: 'openai-completions', provider: 'spark-host',
    baseUrl: 'https://spark.invalid/v1', reasoning: false, input: ['text'],
    cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 },
    contextWindow: request.context_window, maxTokens: request.max_tokens,
    compat: { supportsDeveloperRole: false, supportsStore: false, supportsReasoningEffort: false, maxTokensField: 'max_tokens' } };
  const runtime = await sdk.ModelRuntime.create({ credentials: new ai.InMemoryCredentialStore(),
    modelsPath: null, allowModelNetwork: false, refreshOnCreate: false });
  runtime.registerNativeProvider(ai.createProvider({ id: 'spark-host', models: [model],
    auth: { apiKey: { name: 'Host transport', resolve: async () => ({ auth: { apiKey: 'host-transport' } }) } },
    api: openAICompletionsApi() }));
  const settings = sdk.SettingsManager.inMemory({ enableInstallTelemetry: false, enableAnalytics: false,
    enableSkillCommands: false, cacheWarming: 'off', retry: { enabled: false, maxRetries: 0 },
    compaction: { enabled: request.kind === 'chat', reserveTokens: Math.min(1024, request.context_window / 4),
      keepRecentTokens: Math.floor(request.context_window / 2) }, images: { blockImages: true, autoResize: false },
    defaultTools: [], codemode: { mode: 'off' } });
  const manager = sdk.SessionManager.inMemory('/');
  const messages = canonicalMessages();
  const prompt = messages.pop();
  if (!prompt || prompt.role !== 'user') throw new Error('Canonical history needs a final user message');
  for (const message of messages) manager.appendMessage(message);
  const resourceLoader = {
    getExtensions: () => ({ extensions: [], errors: [], runtime: sdk.createExtensionRuntime() }),
    getSkills: () => ({ skills: [], diagnostics: [] }), getPrompts: () => ({ prompts: [], diagnostics: [] }),
    getThemes: () => ({ themes: [], diagnostics: [] }), getAgentsFiles: () => [],
    getSystemPrompt: () => request.system, getSystemPromptSource: () => undefined,
    getAppendSystemPrompt: () => [], getAppendSystemPromptSources: () => [], extendResources() {}, async reload() {},
  };
  const tools = (request.tools || []).map(t => ({ name: t.name, label: t.name, description: t.description,
    parameters: { type: 'object', properties: t.properties, required: t.required, additionalProperties: false },
    execute: async (_id, args) => {
      if (chosen) throw new Error('Only one proposal is allowed');
      chosen = { name: t.name, arguments: args };
      return { content: [{ type: 'text', text: 'Proposal handed to the host; not executed.' }], details: {}, terminate: true };
    } }));
  ({ session } = await sdk.createAgentSession({ cwd: '/', agentDir: process.cwd(), modelRuntime: runtime,
    model, thinkingLevel: 'off', resourceLoader, sessionManager: manager, settingsManager: settings,
    tools: tools.map(t => t.name), customTools: tools, noTools: 'builtin' }));
  session.agent.toolExecution = 'sequential';
  session.agent.identity = { attribution: null };
  const previousPrepare = session.agent.prepareNextTurnWithContext;
  session.agent.prepareNextTurnWithContext = async (turn, signal) => {
    const prepared = await previousPrepare(turn, signal);
    // The host supplies identity and any real working directory. Pi's
    // private process cwd is an isolation detail, not conversation context.
    return { ...prepared, context: { ...(prepared?.context || turn.context), systemPrompt: request.system } };
  };
  // streamSimple reserves a fixed 4096 tokens and can silently reduce a
  // local model's answer to one token. Spark owns reply budgets; the real
  // context window remains available to Pi's session compaction.
  session.agent.streamFunction = (m, c, o) => runtime.stream(m, c, { ...o, fetch: hostFetch,
    env: {}, maxTokens: request.max_tokens, temperature: request.temperature,
    toolChoice: request.kind === 'command' ? 'required' : undefined,
    samplingParams: { chat_template_kwargs: { enable_thinking: false }, reasoning_budget_tokens: 0,
      parallel_tool_calls: false }, maxRetries: 0 });
  session.agent.beforeToolCall = async ({ assistantMessage }) => {
    if (assistantMessage.content.filter(c => c.type === 'toolCall').length !== 1)
      return { block: true, reason: 'The host accepts one proposal at a time.', terminate: true };
  };
  const previousFinish = session.agent.finishTurn;
  session.agent.finishTurn = async (turn, signal) => {
    if (chosen) return { action: 'end' };
    return previousFinish?.(turn, signal);
  };
  session.subscribe(event => {
    if (event.type === 'message_end' && event.message.role === 'assistant') {
      lastAssistant = event.message;
      if (visibleText && ['error', 'aborted'].includes(lastAssistant.stopReason)) failedAfterText = true;
    }
    if (request.kind === 'chat' && event.type === 'message_update' && event.assistantMessageEvent.type === 'text_delta') {
      visibleText = visibleText || !!event.assistantMessageEvent.delta;
      send({ event: 'delta', text: event.assistantMessageEvent.delta });
    }
  });
  await session.prompt(prompt.content);
  await session.waitForIdle();
  // Session recovery may remove a failed turn from its message store. An
  // earlier successful answer must never stand in for this request's result.
  const last = lastAssistant;
  const finalText = last?.content?.filter(c => c.type === 'text').map(c => c.text).join('') || '';
  if (failedAfterText) throw new Error('The partial reply is incomplete');
  if (chosen) finish({ choice: chosen, calls: wireCalls });
  else if (request.kind === 'chat' && ['stop', 'length'].includes(last?.stopReason))
    finish({ text: finalText, calls: wireCalls, finish: last.stopReason });
  else if (request.kind === 'task' && last?.stopReason === 'stop'
      && !request.packet.history.some(h => h.decision?.kind === 'step')) {
    const text = finalText;
    if (text) finish({ choice: { name: 'spark_task_answer', arguments: { text: text.slice(0, 500) } }, calls: wireCalls });
    else throw new Error('No decision returned');
  } else throw new Error(last?.stopReason === 'length' ? 'Model response was truncated' : 'No explicit decision returned');
}

input.on('line', line => {
  try {
    if (line.length > 1048576) throw new Error('Host message limit');
    const message = JSON.parse(line);
    if (!request) { request = message; run().catch(() => finish({ error: 'The agent did not return a complete decision.' })).finally(() => {
      session?.dispose(); input.close(); process.exit(0);
    }); }
    else hostResponse(message);
  } catch { session?.dispose(); process.exit(2); }
});
input.on('close', () => { session?.dispose(); process.exit(0); });
