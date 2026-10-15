<p align="center">
  <img src="docs/logo.svg" width="96" height="96" alt="novelterm logo">
</p>

<h1 align="center">novelterm</h1>

<p align="center">Web novels in your terminal. Bring your own sources.</p>

A terminal reader for web novels. novelterm ships without sources. A source is a
`.toml` file that describes how to read one site. You add sources from
repositories or as local files.

## Install

Requires Python 3.12 or newer. Supported platforms: Linux, macOS, Windows.
On Linux and macOS novelterm uses only the Python standard library. On Windows it
installs `windows-curses`, because Python for Windows has no `curses` module.
Use Windows Terminal on Windows; the old console window can show wrong colors.

```
uv tool install --editable .
novelterm
```

## Use

| Screen | Keys |
|---|---|
| Menus | `Up`/`Down` or `j`/`k` move, `Enter` or `Right` open, `Left` / `Esc` / `Backspace` / `q` back, `/` search (long lists) |
| Reader | `Up`/`Down` or `j`/`k` scroll, `Space` / `b` page, `g` / `G` top or bottom, `Right` / `Left` next or previous chapter, `q` back. `Space` at the end of a chapter opens the next chapter. |
| Library | `s` change the sort order, `d` remove the selected novel |
| Long tasks | `q` or `Esc` stops a download or an update check |
| Home | Back keys do not quit. Select **Quit** to close novelterm. |

Home screens:

- **Continue reading**: opens the last chapter at the saved scroll position.
- **Library**: novels you started or added, with the number of unread chapters.
- **Check for updates**: loads the novel page of each library novel and lists the novels with new chapters.
- **Browse sources**: novel list of each installed source, and search when the source supports it.
- **Open a link**: opens a novel or chapter URL with the source that handles its host.
- **Manage sources**: installed sources, repositories, reload, problems.
- **Settings**: reader line width, theme, paragraph spacing, library sort.

Reading:

- A novel goes into the library when you open one of its chapters.
- A chapter is marked as read when you go to the next chapter, or when you leave it at the end.
  The chapter list shows read chapters in grey.
- Unread chapters are the known chapters after your current chapter that are not marked as read.
  novelterm updates the known chapters each time it loads the novel page.

Moved novels: when a saved novel or chapter page returns HTTP 404 from **Continue
reading**, **Library** or **Check for updates**, novelterm offers **Find the novel
again**. You pick the novel from the source's novel list (same title at the top) and
the chapter (novelterm suggests the chapter with the same last URL part). novelterm
then moves your reading position and read markers to the new URLs. Read markers
without a chapter with the same last URL part are dropped.

Offline reading: **Download for offline reading** on a novel page saves chapters to
`DATA/downloads`. Downloaded chapters open without a connection. Downloads are for
your own reading.

## Network

- novelterm waits at least 1 second between two requests to the same host.
- HTTP 429, 500, 502, 503 and 504 are tried again up to 3 times. novelterm uses the
  `Retry-After` header when the site sends it (60 seconds at most), else it waits 2
  and then 4 seconds.
- HTTP 401 and 403 are not tried again. novelterm shows that the site refused the
  request and does not try to get around it.
- Novel lists, novel pages and the last 20 chapters stay in memory until novelterm
  closes. **Check for updates** always loads the novel pages again.

## Settings

`CONFIG/config.toml`. **Settings** in the app writes this file. You can also edit it.

```toml
[reader]
line_width = 80          # 40 to 200
theme = "terminal"       # "terminal", "dark", "light" or "sepia"
paragraph_spacing = 1    # empty lines between paragraphs, 0 to 3

[library]
sort = "last_read"       # "last_read", "title" or "source"
```

The `sepia` theme needs a terminal with 256 colors. Other terminals show the `light`
theme. When the file has an error, novelterm shows the error and uses the defaults.

## Library backup

```
novelterm export-library novelterm-library.json
novelterm import-library novelterm-library.json
```

`import-library` merges the copy into your library. For a novel in both, the newer
reading position is kept and the read markers are combined. Downloads are not part
of the copy.

## Files

| Folder | Linux and macOS | Windows |
|---|---|---|
| Config (`CONFIG`) | `$XDG_CONFIG_HOME/novelterm`, default `~/.config/novelterm` | `%APPDATA%\novelterm` |
| Data (`DATA`) | `$XDG_DATA_HOME/novelterm`, default `~/.local/share/novelterm` | `%LOCALAPPDATA%\novelterm` |

| Path | Content |
|---|---|
| `CONFIG/sources/*.toml` | Local source files. You manage these. |
| `DATA/sources/*.toml` | Source files installed from repositories. novelterm manages these. |
| `DATA/installed.json` | Repository, version and sha256 of each installed source. |
| `DATA/repositories.json` | Saved repository URLs. |
| `DATA/library.json` | Library, reading positions and read markers. |
| `DATA/downloads/` | Chapters downloaded for offline reading. |
| `CONFIG/config.toml` | Settings. |

When a local file and an installed file use the same `identifier`, novelterm uses
the local file. **Manage sources → Problems** lists files that do not load, with
the reason.

## Source file format

```toml
format_version = 1                 # must be 1
identifier = "example-site"        # a-z, 0-9, '-', '_'; stored in the library, do not change
name = "Example Site"
version = "1.0.0"                  # increase for each change you publish
description = "Short text"         # optional
home_url = "https://example.org/"
hosts = ["example.org", "www.example.org"]   # URLs with these hosts use this source

[urls]
# Regular expressions, searched in the URL path. The chapter pattern is tested first.
novel_pattern = "/novel/"
chapter_pattern = "/novel/[^/]+/chapter-"

[novel_list]
page = "https://example.org/novels/"   # page that lists the novels
links = "div.novel-list a"             # links to novel pages; only links that match novel_pattern count

[novel]
title = "h1.novel-title"
status = "div.status"                  # optional; a leading "Status:" is removed
description = "div.summary"            # optional
description_text = "all"               # optional: "all" (default) or "own" (text outside child elements)
chapters = "ul.chapter-list a"         # only links that match chapter_pattern count
locked_chapters = "ul.locked a"        # optional; only counted, never shown
chapter_order = "oldest_first"         # optional: "oldest_first" (default) or "newest_first"

[chapter]
title = "h1.chapter-title"
content = "div.chapter-text"           # chapter body
novel_link = "a.back-to-novel"         # optional; links the chapter to its novel in the library
previous = "a.previous-chapter"        # optional
next = "a.next-chapter"                # optional

[search]                               # optional table
url = "https://example.org/?s={query}" # {query} is replaced by the URL-encoded search text
results = "div.search-results a"       # links to novel pages; only links that match novel_pattern count
```

Selectors support a subset of CSS: `tag`, `.class`, `#id`, combined forms such as
`div.a.b`, descendant (`div a`) and child (`ul > li > a`). The first match is used
for single values.

Chapter text: novelterm uses the `p`, `h1`–`h6`, `blockquote` and `li` children of
the content element. When the content element has none of these, it uses the
lines of its text, which covers sites that separate paragraphs with `<br>`.

Check a source file against the live site:

```
novelterm check-source example-site.toml                       # novel list page
novelterm check-source example-site.toml https://example.org/novel/first
novelterm check-source example-site.toml https://example.org/novel/first/chapter-1
novelterm check-source example-site.toml --search "first"      # [search] table
novelterm check-source example-site.toml URL --html saved.html # use a saved page
```

The command prints the match count of each selector and what novelterm reads from
the page: titles, counts and URLs, never chapter text. It ends with exit code 1 when
a required selector matches nothing or the page gives no novels, chapters or text.

The source format reads server-rendered HTML only. Sites that load chapters with
JavaScript, need a login, or use bot challenges are not supported.

## Repositories

A repository is a static `index.json` on any web host, for example a Git
repository served over HTTPS:

```json
{
  "format_version": 1,
  "name": "Example sources",
  "sources": [
    {
      "identifier": "example-site",
      "name": "Example Site",
      "version": "1.0.0",
      "description": "Short text",
      "file": "sources/example-site.toml",
      "sha256": "<sha256 hex digest of the file>"
    }
  ]
}
```

`file` is relative to the index URL, or an absolute URL. Supported URL schemes:
`https`, `http`, `file`.

Make the index from a folder of source files:

```
novelterm make-index sources/ --output index.json --name "Example sources"
```

`make-index` checks every source file and fails on invalid files or duplicate
identifiers.

Install rules:

- The downloaded file must match the `sha256` in the index.
- The file must be a valid source file, and its `identifier` and `version` must
  match the index entry.
- If a check fails, nothing changes on disk.
- An entry with a higher `version` than the installed one shows as an update.

## Development

```
uv sync
uv run python -m unittest discover -s tests
```

CI runs the tests on Linux, macOS and Windows with Python 3.12 and 3.13. The tests
do not cover the curses screens; check screen changes by hand on each platform.

## Safety

Source files are data. novelterm reads them with `tomllib` and runs no code from
them. A source can only make novelterm download pages from URLs that you open
through it.

novelterm does not include or recommend any repository. You are responsible for
the repositories you add and for following the terms of the sites you read.

## Disclaimer

novelterm is not affiliated with any website, publisher or translation group. The
project contains no novel content, no site-specific source files and no list of
repositories. Support the authors and translators of what you read.

## License

Apache License 2.0. See [LICENSE](LICENSE).
