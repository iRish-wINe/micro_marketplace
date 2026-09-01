[![License](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](https://opensource.org/licenses/Apache-2.0)

# USER

This repository contains the source for a commercial application.

Short description: Commercial app — add project details here (purpose, installation, usage).

Installation
------------

Prerequisites: Git and your project's runtime (e.g., Node.js or Python).

Clone and enter the repository:

```
git clone https://github.com/iRish-wINe/USER.git
cd USER
```

Node.js example:

```
npm install
npm run build
npm start
```

Python example:

```
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
python -m your_package
```

Replace the commands above with those specific to your project.

Usage
-----

Examples for running the application:

Node.js:

```
npm start
# or
node dist/index.js
```

Python:

```
python -m your_package
```

Add command-line options, environment variables, or example configuration snippets here to help users run the app.

Configuration
-------------

The application reads configuration from environment variables or a .env file. Example variables:

```
# Example .env
APP_ENV=production
APP_PORT=8080
DATABASE_URL=postgres://user:pass@localhost:5432/dbname
LOG_LEVEL=info
```

Alternatively, use a config.json / config.yaml file and pass its path via CLI or an env var (e.g., CONFIG_PATH=./config.yaml).

Document any required secrets and recommended defaults here (do not commit secrets).

License
-------

This project is licensed under the Apache License 2.0. See the LICENSE file for details.


Biz Hub Relationship Layer Update

Files included:
- app.py
- templates/index.html
- templates/settings.html
- templates/login.html
- templates/vendor_profile.html
- templates/favorites.html
- templates/promotions.html
- templates/orders.html

Implemented:
1. Vendor business profile with clickable vendor/company names.
2. Business location on vendor accounts.
3. Customer Favorites with unique customer/vendor pairs.
4. Vendor purchase notifications with unread badge and per-vendor order items.
5. Promotion creation/deactivation and active promo display.
6. Customer navigation: Market | Favorites | Orders | Account.
7. Vendor navigation: Market | Orders (unread badge) | My Store | Account.
8. Existing username/theme/settings behavior retained.
9. Settings product ranges are optional for unrelated settings changes; existing ranges are preserved when none are checked.
10. Database migrations are automatic through init_db() for existing marketplace.db files.

Important:
- Replace the project's app.py and the listed templates with these versions.
- Keep the existing static/ directory and marketplace.db.
- The database tables favorites, vendor_notifications and promotions are created automatically at startup.
- Flask was not installed in the isolated execution environment here, so runtime Flask integration testing could not be performed; app.py was syntax-checked with py_compile.
