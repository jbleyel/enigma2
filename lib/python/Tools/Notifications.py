from Screens.MessageBox import MessageBox, NotificationMessageBox, ToastMessage

notifications = []

notificationAdded = []

# notifications which are currently on screen (and might be closed by similiar notifications)
current_notifications = []


def __AddNotification(fnc, screen, id, *args, **kwargs):
	if ".MessageBox'>" in repr(screen):
		kwargs["simple"] = True
	notifications.append((fnc, screen, args, kwargs, id))
	for x in notificationAdded:
		x()


def AddNotification(screen, *args, **kwargs):
	AddNotificationWithCallback(None, screen, *args, **kwargs)


def AddNotificationWithCallback(fnc, screen, *args, **kwargs):
	__AddNotification(fnc, screen, None, *args, **kwargs)


def AddNotificationParentalControl(fnc, screen, *args, **kwargs):
	RemovePopup("Parental control")
	__AddNotification(fnc, screen, "Parental control", *args, **kwargs)


def AddNotificationWithID(id, screen, *args, **kwargs):
	__AddNotification(None, screen, id, *args, **kwargs)


def AddNotificationWithIDCallback(fnc, id, screen, *args, **kwargs):
	__AddNotification(fnc, screen, id, *args, **kwargs)

# Entry to only have one pending item with an id.
# Only use this if you don't mind losing the callback for skipped calls.
#


def AddNotificationWithUniqueIDCallback(fnc, id, screen, *args, **kwargs):
	for x in notifications:
		if x[4] and x[4] == id:    # Already there...
			return
	__AddNotification(fnc, screen, id, *args, **kwargs)

# we don't support notifications with callback and ID as this
# would require manually calling the callback on cancelled popups.


def RemovePopup(id):
	# remove similiar notifications
	for x in notifications:
		if x[4] and x[4] == id:
			print("[Notifications] RemovePopup id = %s" % id)
			notifications.remove(x)

	for x in current_notifications:
		if x[0] == id:
			print("[Notifications] found in current notifications")
			x[1].close()


newNotifications = []


def RemovePopupNew(id):
	for x in newNotifications:
		if x[0] and x[0] == id:
			print("[Notifications] RemovePopup id = %s" % id)
			newNotifications.remove(x)

	NotificationMessageBox.instance.hide()


def AddNotificationNewCallback(*retVal):
	if newNotifications:
		newNotification = newNotifications.pop(0)
		NotificationMessageBox.instance.showMessageBox(**newNotification[2])


def AddNotificationNew(id, *args, **kwargs):
	newNotifications.append((id, args, kwargs))

	if not NotificationMessageBox.instance.shown and newNotifications:
		newNotification = newNotifications.pop(0)
		NotificationMessageBox.instance.showMessageBox(**newNotification[2])


def AddPopup(text, type, timeout, id=None):
	if id is not None:
		RemovePopupNew(id)
		# RemovePopup(id)
	print("[Notifications] AddPopup id = %s" % id)
	# AddNotificationWithID(id, MessageBox, text=text, type=type, timeout=timeout, close_on_any_key=True)
	AddNotificationNew(id, text=text, type=type, timeout=timeout, close_on_any_key=True, callback=AddNotificationNewCallback)


def AddPopupWithCallback(fnc, text, type, timeout, id=None):
	if id is not None:
		RemovePopup(id)
	print("[Notifications] AddPopupWithCallback id = %s" % id)
	AddNotificationWithIDCallback(fnc, id, MessageBox, text=text, type=type, timeout=timeout, close_on_any_key=False)


toats = []


def ShowToast(text, timeout=5, id=None):
	toats.append((text, timeout, id))
	if not ToastMessage.instance.shown and toats:
		toast = toats.pop(0)
		ToastMessage.instance.showToast(text=toast[0], timeout=toast[1])
