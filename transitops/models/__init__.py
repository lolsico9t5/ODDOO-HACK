# -*- coding: utf-8 -*-
# Import order matters: vehicle and driver before trip (trip has Many2one to both).
# Maintenance and fuel/expense reference vehicle, so vehicle loads first.
from . import transitops_vehicle
from . import transitops_driver
from . import transitops_trip
from . import transitops_maintenance
from . import transitops_fuel_log
from . import transitops_expense
