**English** · [Français](WEB_SEARCH.fr.md)

# Web search

With the **Web** option ticked, the model has two tools: `web_chercher` (search) and `web_lire` (read a page). Nothing is sent when the box is unticked or in strict offline mode ([PRIVACY.md](PRIVACY.md)).

> **Honesty.** The whole chain is tested with **fake servers** (a fake SearXNG, a fake Brave, fake pages). **The real SearXNG image and the real Brave API have not been run by the project**: use the **Test the search** button (Settings > Web search) to see what works on your machine.

## Which engine answers

Engines are tried **in this order**; the first one that returns results wins, the others take over if it fails.

| # | Engine | Needs | Why |
|---|---|---|---|
| 1 | **SearXNG** | an instance at your place (a few minutes with Docker, free) | aggregates several engines, no HTML to scrape, **your queries stay under your control** |
| 2 | **Brave Search** | a personal API key (free tier, brave.com/search/api) | independent index, official API |
| 3 | DuckDuckGo | nothing | works out of the box, but its HTML can change or limit robots |
| 4 | Bing | nothing | back-up |

An engine that returns nothing is left alone for 10 minutes; the same search is answered from a 10-minute cache. Results are **cleaned**: tracking parameters (`utm_…`, `fbclid`…) and anchors removed, duplicates dropped, at most two results per site (unless you ask for one site).

## What it costs (light on purpose)

- **One engine per search**: the engines above are a *fallback order*, not four searches at once. If the first answers, nothing else is asked; if it is silent, the next one is tried **after** it, never alongside.
- Besides the engine's answer, Lutin reads the **start** of the first pages (3 by default, `lire=0` to skip): at most **250 KB** each, in parallel, with a 12-second budget.
- **Memory is bounded**: the page cache keeps at most 8 pages and 6 MB (oldest out first); a huge page is not cached.
- **No background process, no new dependency, no polling**: nothing runs between two searches. Only the **Test the search** button queries every engine at once, and only when you click it.
- Cleaning the results takes well under a millisecond.

## What the model can ask

`web_chercher`: `requete` (short keywords), `nombre` (up to 10), `lire` (how many first pages to read at once), **`periode`** (`jour`, `semaine`, `mois`, `an`), **`site`** (e.g. `docs.python.org`), **`actualites`** (news). The language follows the interface. Each answer ends with the engine used, and results carry their **date** when the engine gives one, so the model can cite its sources.

`web_lire`: `url`, `debut` (continue a long page; the page is kept 10 minutes so the continuation is not downloaded again), **`liens`** (the page's links, to explore a site). It reads **web pages, text files and PDFs** (up to 15 MB, same extraction as attachments), skips menus and footers when there is real content, retries once on a passing server error, and follows the page's declared character set.

## Set up SearXNG (recommended)

```
SEARXNG_SECRET=$(openssl rand -hex 32) docker compose -f docker-compose.searxng.yml up -d
```

The file [docker-compose.searxng.yml](../docker-compose.searxng.yml) listens on `127.0.0.1:8080` only, and [docker/searxng/settings.yml](../docker/searxng/settings.yml) enables the **json** format (Lutin reads it; without it SearXNG answers HTML and Lutin tells you to enable it). Then, **from this machine**: Settings > Web search > SearXNG address = `http://127.0.0.1:8080` (`http://searxng:8080` if Lutin runs in the same Docker network), Save, **Test the search**.

**Security.** SearXNG usually lives on your own network, and Lutin normally **refuses every local address** (a booby-trapped page must not read your internal services). The address you set is the **only exception**, only for searching (never for reading pages), and it can only be set **from this machine**, not from a paired device.

## Brave Search

Create a key (free tier) at brave.com/search/api, paste it in Settings > Web search > Brave Search. It is stored in `recherche.json` next to your data, readable by you only (where the system allows), and **never sent back to the page** (only its last four characters). Also settable from this machine only.

## What it cannot do

- **Pages built by JavaScript** (Reddit, many web apps) look empty. Lutin reads what the server announces (title, description) and tells the model to ask you to **copy-paste the text** or **save the page and attach it**. See [FEATURES.md](FEATURES.md).
- **Sites that refuse automated reads** are not worked around, and neither are pages behind a login or a paywall.
- Results depend on the engines: a rate-limited engine is skipped, a down SearXNG falls back to the next one (visible in the test).
