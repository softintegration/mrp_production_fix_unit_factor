Fixing the unit factor used in backorder generation
-----------------------------------------------------
In Odoo,by default the system rely in the assumption that there is no __Quantity done__ in the __Production move__ when generating the __Manufacturing backorder__,because the __Unit factor__ used by the generation method will allways assume that the __Produced qty__ is __Zero__.
When adding features that can break this assumption,the backorders __Production and Component Movements quantities__ calculations will allways return wrong results,
This module aime to fix this issue by replacing the ___generate_backorder_productions unit factor formula__  by ___split_productions unit factor formula__ Method (like what was done in __Odoo 16 & 17__).



