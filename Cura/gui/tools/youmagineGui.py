from __future__ import absolute_import
__copyright__ = "Copyright (C) 2013 David Braam - Released under terms of the AGPLv3 License"

import wx
import threading
import time
import re
import os
import types
import webbrowser
import cStringIO as StringIO

from Cura.util import profile
from Cura.util import youmagine
from Cura.util.meshLoaders import stl
from Cura.util.meshLoaders import amf
from Cura.util.resources import getPathForImage

from Cura.gui.util import webcam

def getClipboardText():
	ret = ''
	try:
		if not wx.TheClipboard.IsOpened():
			wx.TheClipboard.Open()
			do = wx.TextDataObject()
			if wx.TheClipboard.GetData(do):
				ret = do.GetText()
			wx.TheClipboard.Close()
		return ret
	except:
		return ret

class youmagineManager(object):
	def __init__(self, parent, objectScene):
		self._mainWindow = parent
		self._scene = objectScene
		self._ym = youmagine.Youmagine(profile.getPreference('youmagine_token'))

		self._indicatorWindow = workingIndicatorWindow(self._mainWindow)
		self._getAuthorizationWindow = getAuthorizationWindow(self._mainWindow, self._ym)
		self._newDesignWindow = newDesignWindow(self._mainWindow, self, self._ym)

		thread = threading.Thread(target=self.checkAuthorizationThread)
		thread.daemon = True
		thread.start()

	#Do all the youmagine communication in a background thread, because it can take a while and block the UI thread otherwise
	def checkAuthorizationThread(self):
		wx.CallAfter(self._indicatorWindow.showBusy, 'Checking token')
		if not self._ym.isAuthorized():
			wx.CallAfter(self._indicatorWindow.Hide)
			if not self._ym.isHostReachable():
				wx.MessageBox('Failed to contact YouMagine.com', 'YouMagine error.', wx.OK | wx.ICON_ERROR)
				return
			wx.CallAfter(self._getAuthorizationWindow.Show)
			lastTriedClipboard = ''
			while not self._ym.isAuthorized():
				time.sleep(0.1)
				if self._getAuthorizationWindow.abort:
					wx.CallAfter(self._getAuthorizationWindow.Destroy)
					return
				clipboard = getClipboardText()
				if len(clipboard) == 20:
					if clipboard != lastTriedClipboard and re.match('[a-zA-Z0-9]*', clipboard):
						lastTriedClipboard = clipboard
						self._ym.setAuthToken(clipboard)
			profile.putPreference('youmagine_token', self._ym.getAuthToken())
			wx.CallAfter(self._getAuthorizationWindow.Hide)
			wx.CallAfter(self._getAuthorizationWindow.Destroy)
			wx.MessageBox('Cura is now authorized to share on YouMagine', 'YouMagine.', wx.OK | wx.ICON_INFORMATION)
		wx.CallAfter(self._indicatorWindow.Hide)

		#TODO: Would you like to create a new design or add the model to an existing design?
		wx.CallAfter(self._newDesignWindow.Show)

	def createNewDesign(self, name, description, category, license, imageList, publish):
		thread = threading.Thread(target=self.createNewDesignThread, args=(name, description, category, license, imageList, publish))
		thread.daemon = True
		thread.start()

	def createNewDesignThread(self, name, description, category, license, imageList, publish):
		wx.CallAfter(self._indicatorWindow.showBusy, 'Creating new design on YouMagine...')
		id = self._ym.createDesign(name, description, category, license)
		wx.CallAfter(self._indicatorWindow.Hide)
		if id is None:
			wx.MessageBox('Failed to create a design, nothing uploaded!', 'YouMagine error.', wx.OK | wx.ICON_ERROR)
			return

		for obj in self._scene.objects():
			wx.CallAfter(self._indicatorWindow.showBusy, 'Building model %s...' % (obj.getName()))
			time.sleep(0.1)
			s = StringIO.StringIO()
			filename = obj.getName()
			if obj.canStoreAsSTL():
				stl.saveSceneStream(s, [obj])
				filename += '.stl'
			else:
				amf.saveSceneStream(s, filename, [obj])
				filename += '.amf'

			wx.CallAfter(self._indicatorWindow.showBusy, 'Uploading model %s...' % (filename))
			if self._ym.createDocument(id, filename, s.getvalue()) is None:
				wx.MessageBox('Failed to upload %s!' % (filename), 'YouMagine error.', wx.OK | wx.ICON_ERROR)
			s.close()

		for image in imageList:
			if type(image) in types.StringTypes:
				filename = os.path.basename(image)
				wx.CallAfter(self._indicatorWindow.showBusy, 'Uploading image %s...' % (filename))
				with open(image, "rb") as f:
					if self._ym.createImage(id, filename, f.read()) is None:
						wx.MessageBox('Failed to upload %s!' % (filename), 'YouMagine error.', wx.OK | wx.ICON_ERROR)
			elif type(image) is wx.Bitmap:
				s = StringIO.StringIO()
				if wx.ImageFromBitmap(image).SaveStream(s, wx.BITMAP_TYPE_JPEG):
					if self._ym.createImage(id, "snapshot.jpg", s.getvalue()) is None:
						wx.MessageBox('Failed to upload snapshot!', 'YouMagine error.', wx.OK | wx.ICON_ERROR)
			else:
				print type(image)

		if publish:
			wx.CallAfter(self._indicatorWindow.showBusy, 'Publishing design...')
			self._ym.publishDesign(id)
		wx.CallAfter(self._indicatorWindow.Hide)
		webbrowser.open(self._ym.viewUrlForDesign(id))


class workingIndicatorWindow(wx.Frame):
	def __init__(self, parent):
		super(workingIndicatorWindow, self).__init__(parent, title='YouMagine', style=wx.FRAME_TOOL_WINDOW|wx.FRAME_FLOAT_ON_PARENT|wx.FRAME_NO_TASKBAR|wx.CAPTION)
		self._panel = wx.Panel(self)
		self.SetSizer(wx.BoxSizer())
		self.GetSizer().Add(self._panel, 1, wx.EXPAND)

		self._busyBitmaps = [
			wx.Bitmap(getPathForImage('busy-0.png')),
			wx.Bitmap(getPathForImage('busy-1.png')),
			wx.Bitmap(getPathForImage('busy-2.png')),
			wx.Bitmap(getPathForImage('busy-3.png'))
		]

		self._indicatorBitmap = wx.StaticBitmap(self._panel, -1, wx.EmptyBitmapRGBA(24, 24, red=255, green=255, blue=255, alpha=1))
		self._statusText = wx.StaticText(self._panel, -1, '...')

		self._panel._sizer = wx.GridBagSizer(2, 2)
		self._panel.SetSizer(self._panel._sizer)
		self._panel._sizer.Add(self._indicatorBitmap, (0, 0))
		self._panel._sizer.Add(self._statusText, (0, 1), flag=wx.ALIGN_CENTER_VERTICAL)

		self._busyState = 0
		self._busyTimer = wx.Timer(self)
		self.Bind(wx.EVT_TIMER, self._busyUpdate, self._busyTimer)
		self._busyTimer.Start(100)

	def _busyUpdate(self, e):
		if self._busyState is None:
			return
		self._busyState += 1
		if self._busyState >= len(self._busyBitmaps):
			self._busyState = 0
		self._indicatorBitmap.SetBitmap(self._busyBitmaps[self._busyState])

	def showBusy(self, text):
		self._statusText.SetLabel(text)
		self.Fit()
		self.Centre()
		self.Show()

class getAuthorizationWindow(wx.Frame):
	def __init__(self, parent, ym):
		super(getAuthorizationWindow, self).__init__(parent, title='YouMagine')
		self._panel = wx.Panel(self)
		self.SetSizer(wx.BoxSizer())
		self.GetSizer().Add(self._panel, 1, wx.EXPAND)
		self._ym = ym
		self.abort = False

		self._requestButton = wx.Button(self._panel, -1, 'Request authorization from YouMagine')
		self._authToken = wx.TextCtrl(self._panel, -1, 'Paste token here')

		self._panel._sizer = wx.GridBagSizer(5, 5)
		self._panel.SetSizer(self._panel._sizer)

		self._panel._sizer.Add(wx.StaticBitmap(self._panel, -1, wx.Bitmap(getPathForImage('youmagine-text.png'))), (0,0), span=(1,4), flag=wx.ALIGN_CENTRE | wx.ALL)
		self._panel._sizer.Add(wx.StaticText(self._panel, -1, 'To share your designs on YouMagine\nyou need an account on YouMagine.com\nand authorize Cura to access your account.'), (1, 1))
		self._panel._sizer.Add(self._requestButton, (2, 1), flag=wx.ALL)
		self._panel._sizer.Add(wx.StaticText(self._panel, -1, 'This will open a browser window where you can\nauthorize Cura to access your YouMagine account.\nYou can revoke access at any time\nfrom YouMagine.com'), (3, 1), flag=wx.ALL)
		self._panel._sizer.Add(wx.StaticLine(self._panel, -1), (4,0), span=(1,4), flag=wx.EXPAND | wx.ALL)
		self._panel._sizer.Add(self._authToken, (5, 1), flag=wx.EXPAND | wx.ALL)
		self._panel._sizer.Add(wx.StaticLine(self._panel, -1), (6,0), span=(1,4), flag=wx.EXPAND | wx.ALL)

		self.Bind(wx.EVT_BUTTON, self.OnRequestAuthorization, self._requestButton)
		self.Bind(wx.EVT_TEXT, self.OnEnterToken, self._authToken)
		self.Bind(wx.EVT_CLOSE, self.OnClose)

		self.Fit()
		self.Centre()

		self._authToken.SetFocus()
		self._authToken.SelectAll()

	def OnRequestAuthorization(self, e):
		webbrowser.open(self._ym.getAuthorizationUrl())

	def OnEnterToken(self, e):
		self._ym.setAuthToken(self._authToken.GetValue())

	def OnClose(self, e):
		self.abort = True

class newDesignWindow(wx.Frame):
	def __init__(self, parent, manager, ym):
		super(newDesignWindow, self).__init__(parent, title='YouMagine')
		p = wx.Panel(self)
		self.SetSizer(wx.BoxSizer())
		self.GetSizer().Add(p, 1, wx.EXPAND)
		self._manager = manager
		self._ym = ym
		self._cam = webcam.webcam()

		categoryOptions = ym.getCategories()
		licenseOptions = ym.getLicenses()
		self._designName = wx.TextCtrl(p, -1, 'Design name')
		self._designDescription = wx.TextCtrl(p, -1, '', size=(1, 150), style = wx.TE_MULTILINE|wx.TE_PROCESS_TAB)
		self._designLicense = wx.ComboBox(p, -1, licenseOptions[0], choices=licenseOptions, style=wx.CB_DROPDOWN|wx.CB_READONLY)
		self._category = wx.ComboBox(p, -1, categoryOptions[-1], choices=categoryOptions, style=wx.CB_DROPDOWN|wx.CB_READONLY)
		self._publish = wx.CheckBox(p, -1, 'Publish after upload')
		self._shareButton = wx.Button(p, -1, 'Upload')
		self._imageScroll = wx.lib.scrolledpanel.ScrolledPanel(p)

		self._imageScroll.SetSizer(wx.BoxSizer(wx.HORIZONTAL))
		self._addImageButton = wx.Button(self._imageScroll, -1, 'Add...', size=(70,52))
		self._imageScroll.GetSizer().Add(self._addImageButton)
		self._snapshotButton = wx.Button(self._imageScroll, -1, 'Take...', size=(70,52))
		self._imageScroll.GetSizer().Add(self._snapshotButton)
		if not self._cam.hasCamera():
			self._snapshotButton.Hide()
		self._imageScroll.Fit()
		self._imageScroll.SetupScrolling(scroll_x=True, scroll_y=False)
		self._imageScroll.SetMinSize((20, self._imageScroll.GetSize()[1] + wx.SystemSettings_GetMetric(wx.SYS_HSCROLL_Y)))

		self._publish.SetValue(True)
		self._publish.SetToolTipString('Directly publish the design after uploading.\nWithout this check the design will not be public\nuntil you publish it yourself on YouMagine.com')

		s = wx.GridBagSizer(5, 5)
		p.SetSizer(s)

		s.Add(wx.StaticBitmap(p, -1, wx.Bitmap(getPathForImage('youmagine-text.png'))), (0,0), span=(1,6), flag=wx.ALIGN_CENTRE | wx.ALL)
		s.Add(wx.StaticText(p, -1, 'Design name:'), (1, 1))
		s.Add(self._designName, (1, 2), span=(1,2), flag=wx.EXPAND|wx.ALL)
		s.Add(wx.StaticText(p, -1, 'Description:'), (2, 1))
		s.Add(self._designDescription, (2, 2), span=(1,2), flag=wx.EXPAND|wx.ALL)
		s.Add(wx.StaticText(p, -1, 'Category:'), (3, 1))
		s.Add(self._category, (3, 2), span=(1,2), flag=wx.ALL)
		s.Add(wx.StaticText(p, -1, 'License:'), (4, 1))
		s.Add(self._designLicense, (4, 2), span=(1,2), flag=wx.ALL)
		s.Add(wx.StaticLine(p, -1), (5,0), span=(1,6), flag=wx.EXPAND|wx.ALL)
		s.Add(wx.StaticText(p, -1, 'Images:'), (6, 1))
		s.Add(self._imageScroll, (6, 2), span=(1, 2), flag=wx.EXPAND|wx.ALL)
		s.Add(wx.StaticLine(p, -1), (7,0), span=(1,6), flag=wx.EXPAND|wx.ALL)
		s.Add(self._shareButton, (8, 2), flag=wx.ALL)
		s.Add(self._publish, (8, 3), flag=wx.ALL|wx.ALIGN_CENTER_VERTICAL)

		s.AddGrowableRow(2)
		s.AddGrowableCol(3)

		self.Bind(wx.EVT_BUTTON, self.OnShare, self._shareButton)
		self.Bind(wx.EVT_BUTTON, self.OnAddImage, self._addImageButton)
		self.Bind(wx.EVT_BUTTON, self.OnTakeImage, self._snapshotButton)

		self.Fit()
		self.Centre()

		self._designDescription.SetMinSize((1,1))
		self._designName.SetFocus()
		self._designName.SelectAll()

	def OnShare(self, e):
		if self._designName.GetValue() == '':
			wx.MessageBox('The name cannot be empty', 'New design error.', wx.OK | wx.ICON_ERROR)
			self._designName.SetFocus()
			return
		if self._designDescription.GetValue() == '':
			wx.MessageBox('The description cannot be empty', 'New design error.', wx.OK | wx.ICON_ERROR)
			self._designDescription.SetFocus()
			return
		imageList = []
		for child in self._imageScroll.GetChildren():
			if hasattr(child, 'imageFilename'):
				imageList.append(child.imageFilename)
			if hasattr(child, 'imageData'):
				imageList.append(child.imageData)
		self._manager.createNewDesign(self._designName.GetValue(), self._designDescription.GetValue(), self._category.GetValue(), self._designLicense.GetValue(), imageList, self._publish.GetValue())
		self.Destroy()

	def OnAddImage(self, e):
		dlg=wx.FileDialog(self, "Select image file...", style=wx.FD_OPEN|wx.FD_FILE_MUST_EXIST|wx.FD_MULTIPLE)
		dlg.SetWildcard("Image files (*.jpg,*.jpeg,*.png)|*.jpg;*.jpeg;*.png")
		if dlg.ShowModal() == wx.ID_OK:
			for filename in dlg.GetPaths():
				self._addImage(filename)
		dlg.Destroy()

	def OnTakeImage(self, e):
		webcamPhotoWindow(self, self._cam).Show()

	def _addImage(self, image):
		wxImage = None
		if type(image) in types.StringTypes:
			try:
				wxImage = wx.ImageFromBitmap(wx.Bitmap(image))
			except:
				pass
		else:
			wxImage = wx.ImageFromBitmap(image)
		if wxImage is None:
			return

		width, height = wxImage.GetSize()
		if width > 70:
			height = height*70/width
			width = 70
		if height > 52:
			width = width*52/height
			height = 52
		wxImage.Rescale(width, height, wx.IMAGE_QUALITY_NORMAL)
		wxImage.Resize((70, 52), ((70-width)/2, (52-height)/2))
		ctrl = wx.StaticBitmap(self._imageScroll, -1, wx.BitmapFromImage(wxImage))
		if type(image) in types.StringTypes:
			ctrl.imageFilename = image
		else:
			ctrl.imageData = image

		delButton = wx.Button(ctrl, -1, 'X', style=wx.BU_EXACTFIT)
		self.Bind(wx.EVT_BUTTON, self.OnDeleteImage, delButton)

		self._imageScroll.GetSizer().Insert(len(self._imageScroll.GetChildren())-3, ctrl)
		self._imageScroll.Layout()
		self._imageScroll.Refresh()
		self._imageScroll.SetupScrolling(scroll_x=True, scroll_y=False)

	def OnDeleteImage(self, e):
		ctrl = e.GetEventObject().GetParent()
		self._imageScroll.GetSizer().Detach(ctrl)
		ctrl.Destroy()

		self._imageScroll.Layout()
		self._imageScroll.Refresh()
		self._imageScroll.SetupScrolling(scroll_x=True, scroll_y=False)

class webcamPhotoWindow(wx.Frame):
	def __init__(self, parent, cam):
		super(webcamPhotoWindow, self).__init__(parent, title='YouMagine')
		p = wx.Panel(self)
		self.panel = p
		self.SetSizer(wx.BoxSizer())
		self.GetSizer().Add(p, 1, wx.EXPAND)

		self._cam = cam
		self._cam.takeNewImage(False)

		s = wx.GridBagSizer(3, 3)
		p.SetSizer(s)

		self._preview = wx.Panel(p)
		self._cameraSelect = wx.ComboBox(p, -1, self._cam.listCameras()[0], choices=self._cam.listCameras(), style=wx.CB_DROPDOWN|wx.CB_READONLY)
		self._takeImageButton = wx.Button(p, -1, 'Snap image')
		self._takeImageTimer = wx.Timer(self)

		s.Add(self._takeImageButton, pos=(1, 0))
		s.Add(self._cameraSelect, pos=(1, 1))
		s.Add(self._preview, pos=(0, 0), span=(1, 2), flag=wx.EXPAND)

		if self._cam.getLastImage() is not None:
			self._preview.SetMinSize((self._cam.getLastImage().GetWidth(), self._cam.getLastImage().GetHeight()))
		else:
			self._preview.SetMinSize((640, 480))

		self._preview.Bind(wx.EVT_ERASE_BACKGROUND, self.OnCameraEraseBackground)
		self.Bind(wx.EVT_BUTTON, self.OnTakeImage, self._takeImageButton)
		self.Bind(wx.EVT_TIMER, self.OnTakeImageTimer, self._takeImageTimer)
		self.Bind(wx.EVT_COMBOBOX, self.OnCameraChange, self._cameraSelect)

		self.Fit()
		self.Centre()

		self._takeImageTimer.Start(200)

	def OnCameraChange(self, e):
		self._cam.setActiveCamera(self._cameraSelect.GetSelection())

	def OnTakeImage(self, e):
		self.GetParent()._addImage(self._cam.getLastImage())
		self.Destroy()

	def OnTakeImageTimer(self, e):
		self._cam.takeNewImage(False)
		self.Refresh()

	def OnCameraEraseBackground(self, e):
		dc = e.GetDC()
		if not dc:
			dc = wx.ClientDC(self)
			rect = self.GetUpdateRegion().GetBox()
			dc.SetClippingRect(rect)
		dc.SetBackground(wx.Brush(self._preview.GetBackgroundColour(), wx.SOLID))
		if self._cam.getLastImage() is not None:
			self._preview.SetMinSize((self._cam.getLastImage().GetWidth(), self._cam.getLastImage().GetHeight()))
			self.panel.Fit()
			dc.DrawBitmap(self._cam.getLastImage(), 0, 0)
		else:
			dc.Clear()
