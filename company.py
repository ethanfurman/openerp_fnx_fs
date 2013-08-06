from openerp.osv import fields, osv

class res_company(osv.Model):
    _inherit = "res.company"
    _columns = {
            'prefix': fields.char('prefix', size=64, help='where the file system lives'),
            'pattern': fields.char('regex', size=128, help='names that match regex will be tracked'),
            }
res_company()
