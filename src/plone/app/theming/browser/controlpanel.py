import logging
import zipfile
from ConfigParser import SafeConfigParser

from zope.component import getUtility
from zope.component import getMultiAdapter
from zope.publisher.browser import BrowserView

from plone.registry.interfaces import IRegistry
from plone.resource.utils import iterDirectoriesOfType

from plone.app.theming.interfaces import IThemeSettings, RULE_FILENAME, MANIFEST_FILENAME, _
from plone.app.theming.utils import getOrCreatePersistentResourceDirectory, extractThemeInfo

from AccessControl import Unauthorized
from Products.CMFCore.utils import getToolByName
from Products.Five.browser.decode import processInputs
from Products.statusmessages.interfaces import IStatusMessage

logger = logging.getLogger('plone.app.theming')

class ThemingControlpanel(BrowserView):
    
    def __call__(self):
        if self.update():
            return self.index()
        return ''
    
    def update(self):
        processInputs(self.request)
        
        self.settings = getUtility(IRegistry).forInterface(IThemeSettings, False)
        
        self.selectedTheme = None
        self.availableThemes = []
        self.selectedTheme = None
        
        self.errors = {}
        submitted = False
        
        form = self.request.form
        
        if 'form.button.Cancel' in form:
            self.redirect(_(u"Changes canceled."))
            return False
        
        self.availableThemes = self.getAvailableThemes()
        self.selectedTheme = self.getSelectedTheme(self.availableThemes, self.settings.rules)
        
        if 'form.button.BasicSave' in form:
            self.authorize()
            submitted = True
            
            self.settings.enabled = form.get('enabled', False)
            themeSelection = form.get('selectedTheme', None)
            
            if themeSelection != "_other_":
                rules, prefix = self.getRulesAndPrefix(self.availableThemes, themeSelection)
                
                self.settings.rules = rules
                self.settings.absolutePrefix = prefix
            
        if 'form.button.AdvancedSave' in form:
            self.authorize()
            submitted = True
            
            self.settings.readNetwork = form.get('readNetwork', False)
            
            rules = form.get('rules', None)
            prefix = form.get('absolutePrefix', None)
            
            self.settings.rules = rules
            self.settings.absolutePrefix = prefix
        
        if 'form.button.Import' in form:
            self.authorize()
            submitted = True
            
            enableNewTheme = form.get('enableNewTheme', False)
            replaceExisting = form.get('replaceExisting', False)
            themeArchive = form.get('themeArchive', None)
            
            themeZip = None
            performImport = False
            
            try:
                themeZip = zipfile.ZipFile(themeArchive)
            except (zipfile.BadZipfile, zipfile.LargeZipFile,):
                logger.exception("Could not read zip file")
                self.errors['themeArchive'] = _('error_invalid_zip', 
                        default=u"The uploaded file is not a valid Zip archive"
                    )
            
            if themeZip:
                
                themeName, rulesFile, absolutePrefix = None, None, None
                
                try:
                    themeName, rulesFile, absolutePrefix = extractThemeInfo(themeZip)
                except KeyError:
                    self.errors['themeArchive'] = _('error_no_rules_file',
                            u"The uploaded file does not contain a valid theme archive."
                        )
                else:
                    
                    themeContainer = getOrCreatePersistentResourceDirectory()
                    themeExists = themeName in themeContainer
                    
                    if themeExists:
                        if not replaceExisting:
                            self.errors['themeArchive'] = _('error_already_installed',
                                    u"This theme is already installed. Select 'Replace existing theme' and re-upload to replace it."
                                )
                        else:
                            del themeContainer[themeName]
                            performImport = True
                    else:
                        performImport = True
                    
            if performImport:
                themeContainer.importZip(themeZip)
    
                if enableNewTheme:
                    self.settings.rules = u"/++theme++%s/%s" % (themeName, rulesFile,)
        
                    if isinstance(absolutePrefix, str):
                        absolutePrefix = absolutePrefix.decode('utf-8')
        
                    self.settings.absolutePrefix = absolutePrefix
                    self.settings.enabled = True
            
        if submitted and not self.errors:
            self.redirect(_(u"Changes saved."))
            return False
        elif submitted:
            IStatusMessage(self.request).add(_(u"There were errors"), 'error')
        
        return True
    
    def getAvailableThemes(self):
        themes = []
        for directory in iterDirectoriesOfType('theme'):
            if directory.isFile(RULE_FILENAME) or directory.isFile(MANIFEST_FILENAME):
                name = directory.__name__
                title = name.capitalize().replace('-', ' ').replace('.', ' ')
                description = None
                rules = u"/++theme++%s/%s" % (name, RULE_FILENAME,)
                absolutePrefix = u"/++theme++%s" % name
                
                if directory.isFile(MANIFEST_FILENAME):
                    manifest = directory.openFile(MANIFEST_FILENAME)
                    try:
                        parser = SafeConfigParser({
                                'title': title,
                                'description': description,
                                'rules': None,
                                'prefix': absolutePrefix,
                            })
                        parser.readfp(manifest)
                        
                        title = parser.get('theme', 'title')
                        description = parser.get('theme', 'description')
                        
                        manifestRules = parser.get('theme', 'rules')
                        if manifestRules:
                            rules = '/++theme++%s/%s' % (name, manifestRules,)
                        elif not directory.isFile(RULE_FILENAME):
                            # No rules file found
                            continue
                        
                        absolutePrefix = parser.get('theme', 'prefix')
                    except:
                        logger.exception("Unable to read manifest for theme directory %s", name)
                    finally:
                        manifest.close()
                
                if isinstance(rules, str):
                    rules = rules.decode('utf-8')
                if isinstance(absolutePrefix, str):
                    absolutePrefix = absolutePrefix.decode('utf-8')
                
                themes.append({
                    'id': name,
                    'title': title,
                    'description': description,
                    'rules': rules,
                    'absolutePrefix': absolutePrefix,
                })
                
        return themes
    
    def getSelectedTheme(self, themes, rules):
        for item in themes:
            if item['rules'] == rules:
                return item['id']
        return False
    
    def getRulesAndPrefix(self, themes, themeSelection):
        for item in themes:
            if item['id'] == themeSelection:
                return (item['rules'], item['absolutePrefix'],)
        return None, None
    
    def authorize(self):
        authenticator = getMultiAdapter((self.context, self.request), name=u"authenticator")
        if not authenticator.verify():
            raise Unauthorized
    
    def redirect(self, message):
        IStatusMessage(self.request).add(message)
        portalUrl = getToolByName(self.context, 'portal_url')()
        self.request.response.redirect("%s/plone_control_panel" % portalUrl)