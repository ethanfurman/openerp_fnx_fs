{
   'name': 'Fnx File System',
    'version': '0.8',
    'category': 'Generic Modules',
    'description': """\
            Phoenix file management system.
            """,
    'author': 'Emile van Sebille',
    'maintainer': 'Emile van Sebille',
    'website': 'www.openerp.com',
    'depends': [
            'base',
            'fnx',
        ],
    'js': [
        ],
    'css':['static/src/css/field_binary_css.css',],
    'data': [
            'security/security.xml',
            'security/ir.model.access.csv',
        ],
    'test': [],
    'installable': True,
    'active': False,
}

# vim:expandtab:smartindent:tabstop=4:softtabstop=4:shiftwidth=4:
