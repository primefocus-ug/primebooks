class EFRISInterfaceCodes:
    """EFRIS Interface Codes"""
    GET_SERVER_TIME = 'T101'
    CLIENT_INITIALIZATION = 'T102'
    LOGIN = 'T103'
    GET_SYMMETRIC_KEY = 'T104'
    UPLOAD_INVOICE = 'T109'
    APPLY_CREDIT_NOTE = 'T110'
    GET_SYSTEM_DICTIONARY = 'T115'
    QUERY_TAXPAYER = 'T119'
    GOODS_INQUIRY = 'T127'
    UPLOAD_GOODS = 'T130'


class EFRISEnvironments:
    """EFRIS Environment URLs"""
    SANDBOX = 'https://efristest.ura.go.ug/efrisws/ws/taapp/getInformation'
    PRODUCTION = 'https://efrisws.ura.go.ug/ws/taapp/getInformation'


class EFRISBusinessTypes:
    """EFRIS Business Transaction Types"""
    B2C = '1'  # Business to Consumer
    B2B = '0'  # Business to Business
    B2G = '3'  # Business to Government


class EFRISDocumentTypes:
    """EFRIS Document Types"""
    INVOICE = '1'
    CREDIT_NOTE = '2'
    DEBIT_NOTE = '3'
    PROFORMA = '4'
