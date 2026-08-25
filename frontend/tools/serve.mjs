#!/usr/bin/env node
// Minimal static file server for frontend/, used only by tests (the
// Playwright smoke test) and local manual checks. No dependencies, binds
// to 127.0.0.1 only, serves exclusively from frontend/ — never touches
// data/ or anything else in the repository.

import { createServer } from "node:http";
import { readFile, stat } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");

const MIME = {
  ".html": "text/html; charset=utf-8",
  ".js": "text/javascript; charset=utf-8",
  ".mjs": "text/javascript; charset=utf-8",
  ".css": "text/css; charset=utf-8",
  ".json": "application/json; charset=utf-8",
};

export function createStaticServer() {
  return createServer(async (req, res) => {
    try {
      const urlPath = decodeURIComponent(new URL(req.url, "http://localhost").pathname);
      let relPath = urlPath === "/" ? "/shell/index.html" : urlPath;
      const filePath = path.normalize(path.join(ROOT, relPath));
      if (!filePath.startsWith(ROOT)) {
        res.writeHead(403);
        res.end("Forbidden");
        return;
      }
      const info = await stat(filePath);
      const finalPath = info.isDirectory() ? path.join(filePath, "index.html") : filePath;
      const body = await readFile(finalPath);
      const ext = path.extname(finalPath);
      res.writeHead(200, { "Content-Type": MIME[ext] || "application/octet-stream" });
      res.end(body);
    } catch (err) {
      res.writeHead(404);
      res.end("Not found");
    }
  });
}

function main() {
  const server = createStaticServer();
  const port = Number(process.env.PORT) || 4310;
  server.listen(port, "127.0.0.1", () => {
    console.log(`Serving frontend/ at http://127.0.0.1:${port}/shell/index.html`);
  });
}

// fileURLToPath() normalises both sides to the platform's native path
// format before comparing -- a direct `import.meta.url === "file://" +
// process.argv[1]` string comparison never matches on Windows (argv[1]
// is a backslash path like `C:\...`, while import.meta.url is a
// forward-slash, percent-encoded file:// URL), which silently made this
// server exit immediately without starting on every native-Windows run.
if (process.argv[1] && fileURLToPath(import.meta.url) === path.resolve(process.argv[1])) {
  main();
}
