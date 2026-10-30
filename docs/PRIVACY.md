**English** · [Français](PRIVACY.fr.md)

# Privacy

**Lutin sends nothing about you anywhere.** No account, no telemetry, no statistics. Your conversations, memory and files stay on your machine; the only program that receives your messages is the Ollama on your machine (or in your container).

The network contacts Lutin can make, and when:

| Contact | When | What is sent | Turn it off |
|---|---|---|---|
| `api.github.com` (latest release of Lutin) | at start, then once a day at most | an anonymous request (your IP address and Lutin's user agent, as for any web request) | setting « check for updates » (`verifier_maj`), or strict offline mode |
| `raw.githubusercontent.com` (model catalogue) | at start, once a day at most, and when you click « Look for new models » | an anonymous request | same |
| `registry.ollama.ai` (model fingerprints) | with the model update check | an anonymous request naming the models you have installed | same |
| `ollama.com` (model download) | only when **you** install a model (done by Ollama) | what Ollama sends | strict offline mode refuses it |
| DuckDuckGo and the web pages you ask for | only if the « Web » box is ticked, when the model searches or reads a page | the search words, or the page address | untick « Web », or strict offline mode |
| Telegram, your mail server, X (only if **you** enable the matching addon) | while the addon is on | what the addon sends: the replies written for the messages you receive or the posts you approve, and the credentials needed to sign in (stored apart, never logged) | leave the addon off (they all are by default), or strict offline mode |
| GitHub and PyPI | only while running the install scripts or `lutin update` | an anonymous request | do not run them |

**Strict offline mode** (`lutin hors-ligne oui`, the « Offline » box, or `LUTIN_HORS_LIGNE=1`) blocks every contact above; only this machine and Ollama are reached. A test watches the real connections.

What stays on your disk: configuration, conversations, memory, action log (never the file contents nor the command output), backups of modified files. See [SECURITY.md](SECURITY.md) for who can reach the page.

Third-party components: Ollama and the models have their own privacy and licence terms; Lutin ships no model.
