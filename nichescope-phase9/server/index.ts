import express from "express";
import http from "http";
import { createServer } from "http";
import path from "path";
import { fileURLToPath } from "url";

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

async function startServer() {
  const app = express();
  const server = createServer(app);

  // Serve static files from dist/public in production
  const staticPath =
    process.env.NODE_ENV === "production"
      ? path.resolve(__dirname, "public")
      : path.resolve(__dirname, "..", "dist", "public");

  // Keep the production web server on the same Python API used by Vite in development.
  app.use("/api", (req, res) => {
    const upstream = http.request({
      hostname: "127.0.0.1",
      port: 8000,
      path: req.originalUrl,
      method: req.method,
      headers: { ...req.headers, host: "127.0.0.1:8000" },
    }, (apiResponse) => {
      res.writeHead(apiResponse.statusCode ?? 502, apiResponse.headers);
      apiResponse.pipe(res);
    });
    upstream.on("error", () => {
      if (!res.headersSent) res.status(502).json({ detail: "Dashboard API is unavailable. Start the FastAPI service on port 8000." });
      else res.end();
    });
    req.pipe(upstream);
  });

  app.use(express.static(staticPath));

  // Handle client-side routing - serve index.html for all routes
  app.get("*", (_req, res) => {
    res.sendFile(path.join(staticPath, "index.html"));
  });

  const port = process.env.PORT || 3000;

  server.listen(port, () => {
    console.log(`Server running on http://localhost:${port}/`);
  });
}

startServer().catch(console.error);
