FROM python:3.12-slim AS app
WORKDIR /app
COPY pyproject.toml ./
COPY src ./src
RUN pip install --no-cache-dir -e ".[test]"

FROM node:22-slim AS dashboard-build
WORKDIR /dashboard
COPY dashboard/package.json dashboard/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY dashboard/ ./
RUN npm run build

# The default target: the API with the built dashboard served at /dashboard/.
FROM app AS with-dashboard
COPY --from=dashboard-build /dashboard/dist /app/dashboard_dist
