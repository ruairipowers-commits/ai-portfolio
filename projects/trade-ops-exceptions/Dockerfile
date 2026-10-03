FROM node:26-slim AS server
WORKDIR /srv
COPY mcp-server/package*.json ./
RUN npm install --no-audit --no-fund
COPY mcp-server/ ./
RUN npm run build && npm prune --omit=dev

FROM python:3.11-slim
# Node 22.13+ is required (node:sqlite); copy it from the build stage rather than the older distro package.
COPY --from=server /usr/local/bin/node /usr/local/bin/node
WORKDIR /app
COPY pyproject.toml ./
COPY src ./src
RUN pip install --no-cache-dir -e ".[anthropic,aws,postgres]"
COPY . .
COPY --from=server /srv/dist ./mcp-server/dist
COPY --from=server /srv/node_modules ./mcp-server/node_modules
RUN useradd -m app && chown -R app /app
USER app
ENTRYPOINT ["tradeops"]
CMD ["all"]
