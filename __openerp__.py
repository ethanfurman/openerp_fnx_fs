{
   'name': 'Fnx File System',
    'version': '0.7',
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
    'update_xml': [
            'security/security.xml',
            'security/ir.model.access.csv',
            'fs_view.xml',
        ],
    'test': [],
    'installable': True,
    'active': False,
}
