# PMSystem License Deployment

This directory contains deployment-only assets for the authorization service and administration
portal. It is deliberately excluded from the PMSystem Windows installer.

- `production-nginx/`: official offline Linux production package for host Nginx, Dockerized API,
  and Dockerized PostgreSQL. The server never pulls images from a registry.
- `staging/`: isolated local or non-production simulation with separate database, volume, keys,
  administrator, cookie name, and HTTP port.

Real environment files, keys, certificates, database volumes, and backups must remain outside Git.
Neither environment may connect to the PMSystem business SQLite database.
