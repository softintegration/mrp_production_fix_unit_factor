# -*- coding: utf-8 -*-

from odoo import models, fields, api, _
from odoo.exceptions import UserError
from odoo.tools.float_utils import float_compare, float_is_zero, float_round


class MrpProduction(models.Model):
    """ Manufacturing Orders """
    _inherit = 'mrp.production'

    def _generate_backorder_productions(self, close_mo=True):
        backorders = self.env['mrp.production']
        bo_to_assign = self.env['mrp.production']
        for production in self:
            if production.backorder_sequence == 0:  # Activate backorder naming
                production.backorder_sequence = 1
            production.name = self._get_name_backorder(production.name, production.backorder_sequence)
            backorder_mo = production.copy(default=production._get_backorder_mo_vals())
            if close_mo:
                production.move_raw_ids.filtered(lambda m: m.state not in ('done', 'cancel')).write({
                    'raw_material_production_id': backorder_mo.id,
                })
                production.move_finished_ids.filtered(lambda m: m.state not in ('done', 'cancel')).write({
                    'production_id': backorder_mo.id,
                })
            else:
                new_moves_vals = []
                for move in production.move_raw_ids | production.move_finished_ids:
                    if not move.additional:
                        unit_factor = move.product_uom_qty / (production.product_qty or 1)
                        qty_to_split = move.product_uom_qty - unit_factor * production.qty_producing
                        qty_to_split = move.product_uom._compute_quantity(qty_to_split, move.product_id.uom_id,
                                                                          rounding_method='HALF-UP')
                        move_vals = move._split(qty_to_split)
                        if not move_vals:
                            continue
                        if move.raw_material_production_id:
                            move_vals[0]['raw_material_production_id'] = backorder_mo.id
                        else:
                            move_vals[0]['production_id'] = backorder_mo.id
                        new_moves_vals.append(move_vals[0])
                self.env['stock.move'].create(new_moves_vals)
            backorders |= backorder_mo
            if backorder_mo.picking_type_id.reservation_method == 'at_confirm':
                bo_to_assign |= backorder_mo

            # We need to adapt `duration_expected` on both the original workorders and their
            # backordered workorders. To do that, we use the original `duration_expected` and the
            # ratio of the quantity really produced and the quantity to produce.
            ratio = production.qty_producing / production.product_qty
            for workorder in production.workorder_ids:
                workorder.duration_expected = workorder.duration_expected * ratio
            for workorder in backorder_mo.workorder_ids:
                workorder.duration_expected = workorder.duration_expected * (1 - ratio)

        # As we have split the moves before validating them, we need to 'remove' the excess reservation
        if not close_mo:
            raw_moves = self.move_raw_ids.filtered(lambda m: not m.additional)
            raw_moves._do_unreserve()
            for sml in raw_moves.move_line_ids:
                try:
                    q = self.env['stock.quant']._update_reserved_quantity(sml.product_id, sml.location_id, sml.qty_done,
                                                                          lot_id=sml.lot_id, package_id=sml.package_id,
                                                                          owner_id=sml.owner_id, strict=True)
                    reserved_qty = sum([x[1] for x in q])
                    reserved_qty = sml.product_id.uom_id._compute_quantity(reserved_qty, sml.product_uom_id)
                except UserError:
                    reserved_qty = 0
                sml.with_context(bypass_reservation_update=True).product_uom_qty = reserved_qty
            raw_moves._recompute_state()
        backorders.action_confirm()
        bo_to_assign.action_assign()

        # Remove the serial move line without reserved quantity. Post inventory will assigned all the non done moves
        # So those move lines are duplicated.
        backorders.move_raw_ids.move_line_ids.filtered(
            lambda ml: ml.product_id.tracking == 'serial' and ml.product_qty == 0).unlink()

        wo_to_cancel = self.env['mrp.workorder']
        wo_to_update = self.env['mrp.workorder']
        for old_wo, wo in zip(self.workorder_ids, backorders.workorder_ids):
            if old_wo.qty_remaining == 0:
                wo_to_cancel += wo
                continue
            if not wo_to_update or wo_to_update[-1].production_id != wo.production_id:
                wo_to_update += wo
            wo.qty_produced = max(old_wo.qty_produced - old_wo.qty_producing, 0)
            if wo.product_tracking == 'serial':
                wo.qty_producing = 1
            else:
                wo.qty_producing = wo.qty_remaining
        wo_to_cancel.action_cancel()
        for wo in wo_to_update:
            wo.state = 'ready' if wo.next_work_order_id.production_availability == 'assigned' else 'waiting'

        return backorders



    @api.depends('workorder_ids.state', 'move_finished_ids', 'move_finished_ids.quantity_done')
    def _get_produced_qty(self):
        for production in self:
            done_moves = production.move_finished_ids.filtered(lambda x: x.state == 'done' and x.product_id.id == production.product_id.id)
            qty_produced = sum(done_moves.mapped('quantity_done'))
            production.qty_produced = qty_produced
        return True

