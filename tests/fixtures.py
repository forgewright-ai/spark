"""Host facts for tests, never imported by production code."""
import os
import sys


def init_env(root, **overrides):
    """Pin absent init markers; a case's explicit seams always win.

    On macOS a seam pointing at an absent directory selects systemd,
    so leave the seam unset unless the case explicitly asks for it.
    """
    env = {"SPARK_OS": "Darwin" if sys.platform == "darwin" else "Linux",
           "SPARK_VAR_SERVICE": os.path.join(root, "no-service")}
    if overrides.get("SPARK_OS", env["SPARK_OS"]) != "Darwin":
        env["SPARK_ETC_RUNIT"] = os.path.join(root, "no-runit")
    env.update(overrides)
    return env


def chat_readline_unavailable(platform, backend):
    """The chat input hooks support GNU readline, or Apple's libedit."""
    if backend == "no readline":
        return "Python has no readline module"
    if backend == "libedit" and platform != "darwin":
        return "the libedit input hook requires macOS TIOCSTI"
    return ""
