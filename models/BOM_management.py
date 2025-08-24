from odoo import models, fields, api, _
from odoo.exceptions import ValidationError, UserError

from datetime import datetime, timedelta
import logging

_logger = logging.getLogger(__name__)


class EngineeringChange(models.Model):
    _name = 'manufacturing.engineering.change'
    _description = 'Engineering Change Order'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'priority desc, request_date desc'

    name = fields.Char('ECO Number', required=True, default='New', readonly=True, tracking=True)
    sequence = fields.Char('Sequence', default='New', readonly=True, copy=False)
    bom_id = fields.Many2one('mrp.bom', 'BOM', required=True, ondelete='cascade', tracking=True)
    change_type = fields.Selection([
        ('addition', 'Component Addition'),
        ('removal', 'Component Removal'),
        ('modification', 'Component Modification'),
        ('process', 'Process Change'),
        ('routing', 'Routing Change'),
        ('specification', 'Specification Change')
    ], required=True, tracking=True)

    description = fields.Text('Change Description', required=True)
    reason = fields.Html('Reason for Change')
    impact_analysis = fields.Html('Impact Analysis')

    requested_by = fields.Many2one('res.users', 'Requested By', default=lambda self: self.env.user,
                                   readonly=True, tracking=True)
    approved_by = fields.Many2one('res.users', 'Approved By', readonly=True, tracking=True)
    request_date = fields.Date('Request Date', default=fields.Date.today, readonly=True)
    approval_date = fields.Date('Approval Date', readonly=True)

    state = fields.Selection([
        ('draft', 'Draft'),
        ('review', 'Under Review'),
        ('approved', 'Approved'),
        ('implemented', 'Implemented'),
        ('rejected', 'Rejected'),
        ('cancelled', 'Cancelled')
    ], default='draft', tracking=True, required=True)

    effective_date = fields.Date('Effective Date')
    cost_impact = fields.Float('Cost Impact', help="Estimated cost impact of this change")
    priority = fields.Selection([
        ('low', 'Low'),
        ('medium', 'Medium'),
        ('high', 'High'),
        ('critical', 'Critical')
    ], default='medium', required=True, tracking=True)

    # Change Details
    change_line_ids = fields.One2many('manufacturing.engineering.change.line', 'change_id', 'Change Lines')

    # Computed fields
    change_line_count = fields.Integer('Change Lines', compute='_compute_change_line_count')
    days_in_review = fields.Integer('Days in Review', compute='_compute_days_in_review')

    # Additional tracking fields
    reviewer_ids = fields.Many2many('res.users', 'eco_reviewer_rel', 'eco_id', 'user_id',
                                    string='Reviewers')
    implementation_notes = fields.Text('Implementation Notes')
    rejection_reason = fields.Text('Rejection Reason')

    @api.model
    def create(self, vals):
        if vals.get('name', 'New') == 'New':
            vals['name'] = self.env['ir.sequence'].next_by_code('manufacturing.engineering.change') or 'New'
        return super(EngineeringChange, self).create(vals)

    _sql_constraints = [
        ('unique_name', 'unique(name)', 'ECO Number must be unique!'),
    ]

    @api.depends('change_line_ids')
    def _compute_change_line_count(self):
        for record in self:
            record.change_line_count = len(record.change_line_ids)

    @api.depends('request_date', 'state')
    def _compute_days_in_review(self):
        for record in self:
            if record.state == 'review' and record.request_date:
                delta = fields.Date.today() - record.request_date
                record.days_in_review = delta.days
            else:
                record.days_in_review = 0

    @api.model
    def create(self, vals):
        if vals.get('name', 'New') == 'New':
            vals['name'] = self.env['ir.sequence'].next_by_code('manufacturing.engineering.change') or 'New'
        if vals.get('sequence', 'New') == 'New':
            vals['sequence'] = vals['name']
        return super(EngineeringChange, self).create(vals)

    def write(self, vals):
        # Track state changes
        if 'state' in vals:
            old_state = self.state
            new_state = vals['state']
            if old_state != new_state:
                self._track_state_change(old_state, new_state)
        return super(EngineeringChange, self).write(vals)

    def _track_state_change(self, old_state, new_state):
        """Track state changes and send notifications"""
        state_messages = {
            'draft': _('Engineering Change Order created'),
            'review': _('Engineering Change Order submitted for review'),
            'approved': _('Engineering Change Order approved'),
            'implemented': _('Engineering Change Order implemented'),
            'rejected': _('Engineering Change Order rejected'),
            'cancelled': _('Engineering Change Order cancelled')
        }

        message = state_messages.get(new_state, _('State changed to %s') % new_state)
        self.message_post(body=message, message_type='notification')

        # Send notifications to relevant users
        if new_state == 'review':
            self._notify_reviewers()
        elif new_state in ['approved', 'rejected']:
            self._notify_requester()

    def _notify_reviewers(self):
        """Notify reviewers when ECO is submitted for review"""
        if self.reviewer_ids:
            self.activity_schedule(
                'manufacturing_erp_suite.mail_activity_eco_review',
                user_id=self.reviewer_ids[0].id,
                summary=_('Review Engineering Change Order: %s') % self.name,
                note=_('Please review the engineering change order for BOM: %s') % self.bom_id.display_name
            )

    def _notify_requester(self):
        """Notify requester of approval/rejection"""
        if self.requested_by:
            activity_type = 'mail.mail_activity_data_todo'
            summary = _('ECO %s: %s') % (self.name, dict(self._fields['state'].selection)[self.state])
            self.activity_schedule(
                activity_type,
                user_id=self.requested_by.id,
                summary=summary
            )

    @api.constrains('effective_date', 'approval_date')
    def _check_effective_date(self):
        for record in self:
            if record.effective_date and record.approval_date:
                if record.effective_date < record.approval_date:
                    raise ValidationError(_('Effective date cannot be earlier than approval date.'))

    @api.constrains('change_line_ids')
    def _check_change_lines(self):
        for record in self:
            if record.state in ['approved', 'implemented'] and not record.change_line_ids:
                raise ValidationError(_('At least one change line is required for approved/implemented changes.'))

    def action_submit_for_review(self):
        """Submit ECO for review"""
        if not self.change_line_ids and self.change_type in ['addition', 'removal', 'modification']:
            raise UserError(_('Please add change lines before submitting for review.'))

        self.write({'state': 'review'})
        return True

    def action_approve(self):
        """Approve the Engineering Change Order"""
        if not self.env.user.has_group('mrp.group_mrp_manager'):
            raise UserError(_('Only Manufacturing Managers can approve Engineering Change Orders.'))

        self.write({
            'state': 'approved',
            'approved_by': self.env.user.id,
            'approval_date': fields.Date.today()
        })

        # Auto-set effective date if not set
        if not self.effective_date:
            self.effective_date = fields.Date.today()

        return True

    def action_reject(self):
        """Reject the Engineering Change Order"""
        if not self.env.user.has_group('mrp.group_mrp_manager'):
            raise UserError(_('Only Manufacturing Managers can reject Engineering Change Orders.'))

        # Open wizard for rejection reason
        return {
            'name': _('Rejection Reason'),
            'type': 'ir.actions.act_window',
            'res_model': 'manufacturing.eco.rejection.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_eco_id': self.id}
        }

    def action_implement(self):
        """Implement the approved changes"""
        if self.state != 'approved':
            raise UserError(_('Only approved changes can be implemented.'))

        try:
            self._apply_changes_to_bom()
            self.write({
                'state': 'implemented',
                'implementation_notes': _('Changes successfully applied to BOM on %s') % fields.Datetime.now()
            })
            return True
        except Exception as e:
            _logger.error(f"Error implementing ECO {self.name}: {e}")
            raise UserError(_('Error implementing changes: %s') % str(e))

    def action_cancel(self):
        """Cancel the Engineering Change Order"""
        if self.state == 'implemented':
            raise UserError(_('Cannot cancel an implemented change order.'))

        self.write({'state': 'cancelled'})
        return True

    def action_reset_to_draft(self):
        """Reset ECO to draft state"""
        if self.state == 'implemented':
            raise UserError(_('Cannot reset an implemented change order.'))

        self.write({
            'state': 'draft',
            'approved_by': False,
            'approval_date': False,
            'rejection_reason': False
        })
        return True

    def _apply_changes_to_bom(self):
        """Apply the approved changes to the BOM"""
        if not self.change_line_ids:
            return

        for line in self.change_line_ids:
            try:
                if line.action == 'add':
                    self._add_component_to_bom(line)
                elif line.action == 'remove':
                    self._remove_component_from_bom(line)
                elif line.action == 'modify':
                    self._modify_component_in_bom(line)
            except Exception as e:
                _logger.error(f"Error applying change line {line.id}: {e}")
                raise UserError(_('Error applying change for product %s: %s') % (line.product_id.name, str(e)))

    def _add_component_to_bom(self, line):
        """Add component to BOM"""
        # Check if component already exists
        existing_line = self.env['mrp.bom.line'].search([
            ('bom_id', '=', self.bom_id.id),
            ('product_id', '=', line.product_id.id)
        ], limit=1)

        if existing_line:
            raise UserError(
                _('Component %s already exists in BOM %s') % (line.product_id.name, self.bom_id.display_name))

        self.env['mrp.bom.line'].create({
            'bom_id': self.bom_id.id,
            'product_id': line.product_id.id,
            'product_qty': line.new_qty,
            'product_uom_id': line.product_uom_id.id or line.product_id.uom_id.id,
        })

    def _remove_component_from_bom(self, line):
        """Remove component from BOM"""
        bom_line = self.env['mrp.bom.line'].search([
            ('bom_id', '=', self.bom_id.id),
            ('product_id', '=', line.product_id.id)
        ], limit=1)

        if not bom_line:
            raise UserError(_('Component %s not found in BOM %s') % (line.product_id.name, self.bom_id.display_name))

        bom_line.unlink()

    def _modify_component_in_bom(self, line):
        """Modify component in BOM"""
        bom_line = self.env['mrp.bom.line'].search([
            ('bom_id', '=', self.bom_id.id),
            ('product_id', '=', line.product_id.id)
        ], limit=1)

        if not bom_line:
            raise UserError(_('Component %s not found in BOM %s') % (line.product_id.name, self.bom_id.display_name))

        update_vals = {}
        if line.new_qty != line.current_qty:
            update_vals['product_qty'] = line.new_qty
        if line.product_uom_id:
            update_vals['product_uom_id'] = line.product_uom_id.id

        if update_vals:
            bom_line.write(update_vals)

    def action_view_bom(self):
        """View the related BOM"""
        return {
            'type': 'ir.actions.act_window',
            'name': _('Bill of Materials'),
            'res_model': 'mrp.bom',
            'res_id': self.bom_id.id,
            'view_mode': 'form',
            'target': 'current',
        }

    def action_duplicate(self):
        """Duplicate the ECO"""
        new_eco = self.copy({
            'name': 'New',
            'state': 'draft',
            'approved_by': False,
            'approval_date': False,
            'request_date': fields.Date.today(),
            'effective_date': False,
            'implementation_notes': False,
            'rejection_reason': False,
        })

        return {
            'type': 'ir.actions.act_window',
            'res_model': 'manufacturing.engineering.change',
            'res_id': new_eco.id,
            'view_mode': 'form',
            'target': 'current',
        }

    @api.model
    def get_pending_reviews(self):
        """Get ECOs pending review for current user"""
        return self.search([
            ('state', '=', 'review'),
            ('reviewer_ids', 'in', self.env.user.ids)
        ])

    def name_get(self):
        """Custom name display"""
        result = []
        for record in self:
            name = f"{record.name} - {record.bom_id.display_name}"
            result.append((record.id, name))
        return result


class EngineeringChangeLine(models.Model):
    _name = 'manufacturing.engineering.change.line'
    _description = 'Engineering Change Line'
    _order = 'sequence, id'

    sequence = fields.Integer('Sequence', default=10)
    change_id = fields.Many2one('manufacturing.engineering.change', 'Change Order', required=True, ondelete='cascade')
    product_id = fields.Many2one('product.product', 'Product', required=True,
                                 domain=[('type', 'in', ['product', 'consu'])])
    action = fields.Selection([
        ('add', 'Add'),
        ('remove', 'Remove'),
        ('modify', 'Modify')
    ], required=True, default='add')

    current_qty = fields.Float('Current Quantity', default=0.0, digits='Product Unit of Measure')
    new_qty = fields.Float('New Quantity', default=0.0, digits='Product Unit of Measure')
    quantity_diff = fields.Float('Quantity Difference', compute='_compute_quantity_diff', store=True)

    product_uom_id = fields.Many2one('uom.uom', 'Unit of Measure',
                                     related='product_id.uom_id', store=True)

    notes = fields.Text('Notes')
    cost_impact = fields.Float('Cost Impact', compute='_compute_cost_impact', store=True)

    @api.depends('current_qty', 'new_qty')
    def _compute_quantity_diff(self):
        for record in self:
            record.quantity_diff = record.new_qty - record.current_qty

    @api.depends('product_id', 'quantity_diff')
    def _compute_cost_impact(self):
        for record in self:
            if record.product_id and record.quantity_diff:
                record.cost_impact = record.quantity_diff * record.product_id.standard_price
            else:
                record.cost_impact = 0.0

    @api.onchange('product_id')
    def _onchange_product_id(self):
        """Auto-fill current quantity and UOM when product changes"""
        if self.product_id and self.change_id.bom_id:
            existing_line = self.env['mrp.bom.line'].search([
                ('bom_id', '=', self.change_id.bom_id.id),
                ('product_id', '=', self.product_id.id)
            ], limit=1)

            if existing_line:
                self.current_qty = existing_line.product_qty
                self.product_uom_id = existing_line.product_uom_id.id
                if self.action == 'add':
                    self.action = 'modify'
            else:
                self.current_qty = 0.0
                if self.action in ['remove', 'modify']:
                    self.action = 'add'

    @api.constrains('action', 'current_qty', 'new_qty')
    def _check_quantities(self):
        for record in self:
            if record.action == 'add' and record.current_qty > 0:
                raise ValidationError(_('Cannot add a component that already exists. Use modify instead.'))

            if record.action == 'remove' and record.current_qty <= 0:
                raise ValidationError(_('Cannot remove a component that does not exist.'))

            if record.action == 'modify' and record.current_qty <= 0:
                raise ValidationError(_('Cannot modify a component that does not exist.'))

            if record.new_qty < 0:
                raise ValidationError(_('New quantity cannot be negative.'))


class QualitySpecification(models.Model):
    _name = 'manufacturing.quality.specification'
    _description = 'Quality Specification'
    _order = 'sequence, name'

    sequence = fields.Integer('Sequence', default=10)
    name = fields.Char('Specification Name', required=True)
    bom_id = fields.Many2one('mrp.bom', 'BOM', required=True, ondelete='cascade')
    specification_type = fields.Selection([
        ('dimensional', 'Dimensional'),
        ('material', 'Material'),
        ('surface', 'Surface Finish'),
        ('functional', 'Functional'),
        ('visual', 'Visual'),
        ('performance', 'Performance'),
        ('safety', 'Safety'),
        ('environmental', 'Environmental')
    ], required=True)

    description = fields.Text('Description')
    tolerance = fields.Char('Tolerance', help="e.g., ±0.1mm, ±5%")
    test_method = fields.Char('Test Method')
    acceptance_criteria = fields.Html('Acceptance Criteria')

    is_critical = fields.Boolean('Critical Specification', default=False,
                                 help="Critical specifications require special attention during quality control")
    responsible_dept = fields.Selection([
        ('qc', 'Quality Control'),
        ('engineering', 'Engineering'),
        ('production', 'Production'),
        ('inspection', 'Incoming Inspection'),
        ('lab', 'Laboratory')
    ], string='Responsible Department')

    # Additional fields
    measurement_unit = fields.Char('Measurement Unit', help="Unit of measurement for the specification")
    min_value = fields.Float('Minimum Value')
    max_value = fields.Float('Maximum Value')
    target_value = fields.Float('Target Value')

    active = fields.Boolean('Active', default=True)


# Add rejection wizard
class ECORejectionWizard(models.TransientModel):
    _name = 'manufacturing.eco.rejection.wizard'
    _description = 'ECO Rejection Wizard'

    eco_id = fields.Many2one('manufacturing.engineering.change', 'Engineering Change Order', required=True)
    rejection_reason = fields.Text('Rejection Reason', required=True)

    def action_reject(self):
        """Reject the ECO with reason"""
        self.eco_id.write({
            'state': 'rejected',
            'rejection_reason': self.rejection_reason
        })
        return {'type': 'ir.actions.act_window_close'}

class BOMManagement(models.Model):
    _inherit = 'mrp.bom'

    # Version Control
    version = fields.Char('Version', default='1.0')
    parent_bom_id = fields.Many2one('mrp.bom', 'Parent BOM')
    child_bom_ids = fields.One2many('mrp.bom', 'parent_bom_id', 'Child BOMs')

    # Revision tracking
    revision_number = fields.Integer('Revision Number', default=1)
    revision_date = fields.Date('Revision Date', default=fields.Date.today)
    revision_notes = fields.Text('Revision Notes')

    # Engineering Changes
    engineering_change_ids = fields.One2many('manufacturing.engineering.change', 'bom_id', 'Engineering Changes')
    approval_status = fields.Selection([
        ('draft', 'Draft'),
        ('review', 'Under Review'),
        ('approved', 'Approved'),
        ('obsolete', 'Obsolete')
    ], default='draft', tracking=True)

    # Cost Analysis
    material_cost = fields.Float('Material Cost', compute='_compute_costs', store=True)
    labor_cost = fields.Float('Labor Cost', compute='_compute_costs', store=True)
    overhead_cost = fields.Float('Overhead Cost', compute='_compute_costs', store=True)
    total_cost = fields.Float('Total Cost', compute='_compute_costs', store=True)

    # Advanced Features
    complexity_score = fields.Float('Complexity Score', compute='_compute_complexity', store=True)
    sustainability_score = fields.Float('Sustainability Score')

    # Fixed: Added explicit relation table name for self-referential Many2many
    alternate_bom_ids = fields.Many2many(
        'mrp.bom',
        relation='mrp_bom_alternate_rel',  # Explicit relation table name
        column1='bom_id',  # Column for current record
        column2='alternate_bom_id',  # Column for related record
        string='Alternate BOMs'
    )

    # Quality Requirements
    quality_specification_ids = fields.One2many('manufacturing.quality.specification', 'bom_id',
                                                'Quality Specifications')

    # BOM Analytics
    usage_frequency = fields.Integer('Usage Frequency', default=0)
    last_used_date = fields.Date('Last Used Date')
    estimated_lead_time = fields.Float('Estimated Lead Time (Days)', compute='_compute_lead_time')

    @api.depends('bom_line_ids', 'bom_line_ids.product_qty', 'bom_line_ids.product_id.standard_price', 'operation_ids')
    def _compute_costs(self):
        for bom in self:
            material_cost = 0.0
            labor_cost = 0.0

            # Calculate material costs
            for line in bom.bom_line_ids:
                if line.product_id and line.product_qty:
                    line_cost = line.product_qty * line.product_id.standard_price
                    material_cost += line_cost

            # Calculate labor costs
            for operation in bom.operation_ids:
                if operation.time_cycle and hasattr(operation, 'workcenter_id') and operation.workcenter_id:
                    if hasattr(operation.workcenter_id, 'costs_hour'):
                        op_cost = operation.time_cycle * operation.workcenter_id.costs_hour / 60
                        labor_cost += op_cost

            # Calculate overhead (20% of material + labor)
            overhead_cost = (material_cost + labor_cost) * 0.2

            bom.material_cost = material_cost
            bom.labor_cost = labor_cost
            bom.overhead_cost = overhead_cost
            bom.total_cost = material_cost + labor_cost + overhead_cost

    @api.depends('bom_line_ids', 'operation_ids')
    def _compute_complexity(self):
        for bom in self:
            try:
                component_complexity = len(bom.bom_line_ids) * 1.0
                operation_complexity = len(bom.operation_ids) * 1.5
                level_complexity = bom._get_bom_levels() * 2.0
                bom.complexity_score = component_complexity + operation_complexity + level_complexity
            except Exception as e:
                _logger.error(f"Error computing complexity for BOM {bom.id}: {e}")
                bom.complexity_score = 0.0

    @api.depends('bom_line_ids', 'bom_line_ids.product_id')
    def _compute_lead_time(self):
        for bom in self:
            max_lead_time = 0.0
            for line in bom.bom_line_ids:
                if line.product_id and hasattr(line.product_id, 'sale_delay'):
                    max_lead_time = max(max_lead_time, line.product_id.sale_delay)
            bom.estimated_lead_time = max_lead_time

    def _get_bom_levels(self):
        """Calculate BOM hierarchy levels"""
        max_level = 0
        processed_boms = set()

        def get_level_recursive(bom, current_level=0):
            if bom.id in processed_boms:
                return current_level  # Avoid infinite recursion
            processed_boms.add(bom.id)

            level = current_level
            for line in bom.bom_line_ids:
                if line.product_id.bom_ids:
                    child_bom = line.product_id.bom_ids[0]
                    child_level = get_level_recursive(child_bom, current_level + 1)
                    level = max(level, child_level)
            return level

        return get_level_recursive(self)

    def action_approve_bom(self):
        """Approve BOM for production use"""
        self.write({
            'approval_status': 'approved',
            'revision_date': fields.Date.today()
        })

    def action_create_new_revision(self):
        """Create a new revision of the BOM"""
        new_revision = self.copy({
            'version': f"{self.version}.{self.revision_number + 1}",
            'revision_number': self.revision_number + 1,
            'parent_bom_id': self.id,
            'approval_status': 'draft',
            'revision_date': fields.Date.today()
        })

        return {
            'type': 'ir.actions.act_window',
            'res_model': 'mrp.bom',
            'res_id': new_revision.id,
            'view_mode': 'form',
            'target': 'current',
        }

    def action_obsolete_bom(self):
        """Mark BOM as obsolete"""
        self.write({'approval_status': 'obsolete'})

    def action_view_engineering_changes(self):
        """View engineering changes for this BOM"""
        return {
            'type': 'ir.actions.act_window',
            'name': 'Engineering Changes',
            'res_model': 'manufacturing.engineering.change',
            'view_mode': 'tree,form',
            'domain': [('bom_id', '=', self.id)],
            'context': {'default_bom_id': self.id}
        }

    @api.model
    def get_cost_breakdown(self, bom_id):
        """Get detailed cost breakdown for a BOM"""
        bom = self.browse(bom_id)
        breakdown = {
            'material_costs': [],
            'labor_costs': [],
            'total_material': bom.material_cost,
            'total_labor': bom.labor_cost,
            'total_overhead': bom.overhead_cost,
            'grand_total': bom.total_cost
        }

        # Material cost breakdown
        for line in bom.bom_line_ids:
            if line.product_id:
                breakdown['material_costs'].append({
                    'product': line.product_id.name,
                    'qty': line.product_qty,
                    'unit_cost': line.product_id.standard_price,
                    'total_cost': line.product_qty * line.product_id.standard_price
                })

        # Labor cost breakdown
        for operation in bom.operation_ids:
            if hasattr(operation, 'workcenter_id') and operation.workcenter_id:
                if hasattr(operation.workcenter_id, 'costs_hour'):
                    breakdown['labor_costs'].append({
                        'operation': operation.name,
                        'workcenter': operation.workcenter_id.name,
                        'time_hours': operation.time_cycle / 60,
                        'hourly_rate': operation.workcenter_id.costs_hour,
                        'total_cost': operation.time_cycle * operation.workcenter_id.costs_hour / 60
                    })

        return breakdown
