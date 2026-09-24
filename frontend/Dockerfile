# Frontend (Next.js) development image (docs/ROADMAP.md Phase 1.6).
# Mirrors saas-os/frontend's own Dockerfile shape exactly. No secret is
# ever baked into this image. frontend/.dockerignore keeps a host-local
# node_modules/.next out of the build context -- without it, `COPY . .`
# below would copy host-built (possibly wrong-platform) native modules
# into the image.

FROM node:22-slim

WORKDIR /app

# Give the pre-existing non-root `node` user ownership of the (still-
# empty) app directory before installing/building, so npm's own output
# (node_modules/, .next/) is node-owned from the start.
RUN chown node:node /app
USER node

# package-lock.json copied alongside package.json so `npm ci` installs
# deterministically from the committed lockfile.
COPY --chown=node:node package.json package-lock.json ./
RUN npm ci

COPY --chown=node:node . .

# NEXT_PUBLIC_* is inlined into the client bundle at this build step
# (Next.js convention -- lib/api/config.ts's own docstring), so it must
# be a build ARG, not a container ENV set later at `docker compose up`.
# Never a secret. docker-compose.yml's `frontend.build.args` supplies
# this from the local single-origin edge's origin.
ARG NEXT_PUBLIC_API_URL
ENV NEXT_PUBLIC_API_URL=$NEXT_PUBLIC_API_URL

RUN npm run build

CMD ["npm", "start"]
