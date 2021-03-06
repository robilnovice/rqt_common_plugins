#! /usr/bin/env python

from python_qt_binding.QtGui import QLabel, QStyle


class StatusIndicator(QLabel):
    def __init__(self, *args):
        super(StatusIndicator, self).__init__(*args)
        self.set_stopped()

    def set_running(self):
        self.setPixmap(
           self.style().standardIcon(QStyle.SP_DialogApplyButton).pixmap(16))

    def set_starting(self):
        self.setPixmap(self.style().standardIcon(
                                      QStyle.SP_DialogResetButton).pixmap(16))

    def set_stopping(self):
        self.setPixmap(self.style().standardIcon(
                                      QStyle.SP_DialogResetButton).pixmap(16))

    def set_stopped(self):
        self.setText(" ")

    def set_died(self):
        self.setPixmap(self.style().standardIcon(
                                      QStyle.SP_MessageBoxCritical).pixmap(16))
