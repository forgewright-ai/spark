# The tour

This document is not tied to a spark release. It is kept up to date
as spark changes.

13 small things to try in your first hour. Some use a spark app or
another tool. Skip those you have not installed. `Alt-s` is Option-s
on a Mac.

## The prompt line

1. Ask the shell:

   ```
   ? what is eating my disk
   ```

   The command lands in your line, with a hint above it. `Enter` runs
   it. A `!` in the hint means read it first.

2. Run a command with a typo, such as `git pushh`. Then press `Esc s`
   on the empty line. spark explains the error. Press `Esc s` again
   for the fix.

3. Follow up on the last answer with `??`:

   ```
   ?? how do I change the model
   ```

## The editor

These use micro with spark-micro (see `docs/APPS.md`).

4. Open an empty file with `micro poem.md`. Press `Alt-s` and type:

   ```
   spark> a short poem about this machine
   ```

5. Press `Alt-s`, then `?` alone. A review opens in a pane on the
   right. A quote that is not in your text is marked
   `[not in the text]`.

6. Select a stanza, press `Alt-s` and type `make it rhyme`. The new
   text comes back selected. `Ctrl-Z` undoes it.

7. In a second terminal, run `spark edit --watch poem.md`. Each time
   you save, a comment appears.

## Reading

8. Ask a man page:

   ```
   man ls | spark read how do I sort by size
   ```

   Each line of the answer quotes the page. When the page has no
   answer, spark says so.

9. Practise the commands:

   ```
   spark drill --name spark < ~/.spark/docs/CHEATSHEET.txt
   ```

   You get one question at a time. A question you miss comes back on
   a later day.

10. On Linux, watch a log:

    ```
    journalctl -f | spark watch anything that fails
    ```

    spark stays quiet until a line matches. Then it prints one line
    that quotes it.

## Make it yours

11. Run `spark awaken` and pick a temperament. spark gets a
    personality and a face. `spark look off` turns the look off.

12. Give spark a fact, then chat:

    ```
    spark memory add "short answers, and call me by name"
    spark chat
    ```

    In the chat, `/read @notes.txt what is due this week` answers from
    the file. `/copy` puts the reply on your clipboard.

13. Run `spark serve --login`. Open the address it prints on your
    phone, on the same network, and log in. Your chats are there. The
    traffic is plain HTTP, so use a network you trust.

## Next

`spark <TAB>` completes commands. `docs/CHEATSHEET.txt` lists every
command on one page.
