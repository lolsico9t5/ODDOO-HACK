# -*- coding: utf-8 -*-
# TransitOps — Smart Transport Operations Management
# Fully custom module (does NOT depend on Odoo's native 'fleet' module).
# This deliberate choice gives complete control over the data model, workflows,
# and UI without inheriting fleet's schema constraints or opinionated views.

{
    'name': 'TransitOps - Smart Transport Operations',
    'version': '17.0.1.0.0',
    'category': 'Operations/Fleet',
    'summary': 'End-to-end transport operations: vehicles, drivers, trips, maintenance, fuel & analytics.',
    'description': """
TransitOps
==========
A centralized platform for managing the complete lifecycle of transport operations.

Features:
- Vehicle Registry with lifecycle tracking
- Driver & Safety Profile management
- Trip Dispatching with hard business-rule enforcement
- Maintenance Workflow automation
- Fuel & Expense tracking
- Operational Analytics & KPI dashboards
- Role-Based Access Control (Fleet Manager, Dispatcher, Safety Officer, Financial Analyst)
    """,
    'author': 'TransitOps Development Team',
    'website': 'https://www.transitops.example.com',
    'license': 'LGPL-3',
    'depends': [
        'base',
        'mail',
        'board',
        'web',
    ],
    # Data loading order is critical:
    # 1. Security groups must exist before access rules reference them.
    # 2. ir.model.access.csv must load after groups and models are registered.
    # 3. Sequence data must load before any views that trigger default_get.
    # 4. Views load last; menus load after all actions they reference exist.
    'data': [
        'security/ir.model.category.xml',
        'security/transitops_security.xml',
        'security/ir.model.access.csv',
        'data/sequence_data.xml',
        'views/transitops_views.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'transitops/static/src/css/transitops.css',
        ],
    },
    'images': ['static/description/icon.png'],
    'application': True,
    'installable': True,
    'auto_install': False,
}
