from Acquisition import aq_inner
from AccessControl import getSecurityManager
from Products.CMFCore.utils import getToolByName
from Products.Five.browser import BrowserView
from Products.Five.browser.pagetemplatefile import ViewPageTemplateFile
from plone.namedfile.file import NamedBlobFile
from plone.registry.interfaces import IRegistry
from plone.uuid.interfaces import IUUID
from plone.app.uuid.utils import uuidToObject
from z3c.form import form
from zope.component import getMultiAdapter
from zope.component import getUtility
from onlyoffice.connector.core.config import Config
from onlyoffice.connector.core import fileUtils
from onlyoffice.connector.core import utils
from urllib.request import urlopen

import logging
import json

logger = logging.getLogger("Plone")

class Edit(form.EditForm):
    def isAvailable(self):
        filename = self.context.file.filename
        return fileUtils.canEdit(filename)

    cfg = None
    editorCfg = None

    def __call__(self):
        self.cfg = Config(getUtility(IRegistry))
        self.editorCfg = get_config(self, True)
        if not self.editorCfg:
            index = ViewPageTemplateFile("templates/error.pt")
            return index(self)
        return self.index()

class View(BrowserView):
    def isAvailable(self):
        filename = self.context.file.filename
        return fileUtils.canView(filename)

    cfg = None
    editorCfg = None

    def __call__(self):
        self.cfg = Config(getUtility(IRegistry))
        self.editorCfg = get_config(self, False)
        if not self.editorCfg:
            index = ViewPageTemplateFile("templates/error.pt")
            return index(self)
        return self.index()

def get_config(self, forEdit):
    def viewURLFor(self, item):
        cstate = getMultiAdapter((item, item.REQUEST), name='plone_context_state')
        return cstate.view_url()

    def portal_state(self):
        context = aq_inner(self.context)
        portal_state = getMultiAdapter((context, self.request), name=u'plone_portal_state')
        return portal_state

    canEdit = forEdit and bool(getSecurityManager().checkPermission('Modify portal content', self.context))

    filename = self.context.file.filename
    if not fileUtils.canView(filename) or (forEdit and not fileUtils.canEdit(filename)):
        # self.request.response.status = 500
        # self.request.response.setHeader('Location', self.viewURLFor(self.context))
        return None

    state = portal_state(self)
    user = state.member()
    config = {
        'type': 'desktop',
        'documentType': fileUtils.getFileType(filename),
        'document': {
            'title': filename,
            'url': self.context.absolute_url() + '/@@download',
            'fileType': fileUtils.getFileExt(filename)[1:],
            'key': utils.getDocumentKey(self.context),
            'info': {
                'author': self.context.creators[0],
                'created': str(self.context.creation_date)
            },
            'permissions': {
                'edit': canEdit
            }
        },
        'editorConfig': {
            'mode': 'edit' if canEdit else 'view',
            'lang': state.language(),
            'user': {
                'id': user.getId(),
                'name': user.getUserName()
            },
            'customization': {
                'about': True,
                'feedback': True
            }
        }
    }
    if canEdit:
        context = self.context.aq_base
        uuid = IUUID(context, None)
        portal_url = getToolByName(context, "portal_url")
        portal = portal_url.getPortalObject()
        config['editorConfig']['callbackUrl'] = portal.absolute_url() + "/onlyoffice-callback?uuid=%s" % uuid

    dumped = json.dumps(config)
    logger.debug("get_config\n" + dumped)
    return dumped

class Callback(BrowserView):
    def __call__(self):
        self.request.response.setHeader('Content-Type', 'application/json')

        context = uuidToObject(self.request.QUERY_STRING.split("=")[1])

        error = None
        response = {}

        try:
            body = json.loads(self.request.get('BODY'))
            logger.debug("callback body:\n" + json.dumps(body))

            if body["key"] != utils.getDocumentKey(self.context):
                logger.debug("key different:" +  body["key"] + " - " + utils.getDocumentKey(self.context))
            else:
                logger.debug("same key")
            status = body['status']
            download = body.get('url')

            if (status == 2) | (status == 3): # mustsave, corrupted

                logger.debug("Old key:" + utils.getDocumentKey(context))

                context.file = NamedBlobFile(urlopen(download).read(), filename=context.file.filename)
                context.reindexObject()

                logger.debug("New key:" + utils.getDocumentKey(context))
                logger.debug("Document saved and reindexed")

        except Exception as e:
            error = str(e)
            logger.debug("Error: " + error)

        if error:
            response['error'] = 1
            response['message'] = error
            self.request.response.status = 500
        else:
            response['error'] = 0
            self.request.response.status = 200
        dumped = json.dumps(response)
        logger.debug("response:" + dumped)
        return dumped
