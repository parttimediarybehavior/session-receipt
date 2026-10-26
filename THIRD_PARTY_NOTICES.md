# Third-party notices

## ccusage 20.0.38 (pinned in `package.json`)

Session Receipt runs the `ccusage` command-line tool as a subprocess. It is not
copied into this repository. Claude Code installs it with the plugin; elsewhere, install it
with `npm ci`.

- npm package `ccusage` 20.0.38, license field: MIT
- native binary package `@ccusage/ccusage-linux-x64` 20.0.38, license field: MIT
  (other platforms use the matching `@ccusage/ccusage-<platform>` package)

The ccusage license, reproduced verbatim from `node_modules/ccusage/LICENSE`:

----

MIT License

Copyright (c) 2025 ryoppippi

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.

----

## Environmental scenario sources

`session_receipt/SOURCES.md` lists the published studies (GOOGLE, EPOCH, JEGHAM, ...)
behind the optional `--env` scenarios. Those are cited, not redistributed.

## Pricing

`pricing/reference.json` records Anthropic's published list prices as read on the dates
stated in the file. Prices belong to Anthropic.
