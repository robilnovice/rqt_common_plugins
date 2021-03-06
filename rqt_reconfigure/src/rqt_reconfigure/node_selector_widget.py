# Software License Agreement (BSD License)
#
# Copyright (c) 2012, Willow Garage, Inc.
# All rights reserved.
#
# Redistribution and use in source and binary forms, with or without
# modification, are permitted provided that the following conditions
# are met:
#
#  * Redistributions of source code must retain the above copyright
#    notice, this list of conditions and the following disclaimer.
#  * Redistributions in binary form must reproduce the above
#    copyright notice, this list of conditions and the following
#    disclaimer in the documentation and/or other materials provided
#    with the distribution.
#  * Neither the name of Willow Garage, Inc. nor the names of its
#    contributors may be used to endorse or promote products derived
#    from this software without specific prior written permission.
#
# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS
# "AS IS" AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT
# LIMITED TO, THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS
# FOR A PARTICULAR PURPOSE ARE DISCLAIMED. IN NO EVENT SHALL THE
# COPYRIGHT OWNER OR CONTRIBUTORS BE LIABLE FOR ANY DIRECT, INDIRECT,
# INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING,
# BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES;
# LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER
# CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT
# LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN
# ANY WAY OUT OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE
# POSSIBILITY OF SUCH DAMAGE.
#
# Author: Isaac Saito

from __future__ import division

from collections import OrderedDict
import os
import time

import dynamic_reconfigure as dyn_reconf
from python_qt_binding import loadUi
from python_qt_binding.QtCore import Qt, Signal
from python_qt_binding.QtGui import (QHeaderView, QItemSelectionModel,
                                     QStandardItemModel, QWidget)
import rospkg
import rospy
import rosservice

from rqt_py_common.rqt_ros_graph import RqtRosGraph
from rqt_reconfigure.filter_children_model import FilterChildrenModel
from rqt_reconfigure.treenode_qstditem import TreenodeQstdItem
from rqt_reconfigure.treenode_item_model import TreenodeItemModel


class NodeSelectorWidget(QWidget):
    _COL_NAMES = ['Node']

    # public signal
    sig_node_selected = Signal(str)

    def __init__(self):
        super(NodeSelectorWidget, self).__init__()
        self.stretch = None

        rp = rospkg.RosPack()
        ui_file = os.path.join(rp.get_path('rqt_reconfigure'), 'resource',
                               'node_selector.ui')
        loadUi(ui_file, self)

        # List of the available nodes. Since the list should be updated over
        # time and we don't want to create node instance per every update
        # cycle, This list instance should better be capable of keeping track.
        self._nodeitems = OrderedDict()
        # Dictionary. 1st elem is node's GRN name,
        # 2nd is TreenodeQstdItem instance.
        # TODO: Needs updated when nodes list updated.

        #  Setup treeview and models
        self._item_model = TreenodeItemModel()
        self._rootitem = self._item_model.invisibleRootItem()  # QStandardItem

        self._nodes_previous = None

        # Calling this method updates the list of the node.
        # Initially done only once.
        self._update_nodetree_pernode()

        # TODO(Isaac): Needs auto-update function enabled, once another
        #             function that updates node tree with maintaining
        #             collapse/expansion  state. http://goo.gl/GuwYp can be a
        #             help.

        self._collapse_button.pressed.connect(
                                          self._node_selector_view.collapseAll)
        self._expand_button.pressed.connect(self._node_selector_view.expandAll)

        # Filtering preparation.
        self._proxy_model = FilterChildrenModel(self)
        self._proxy_model.setDynamicSortFilter(True)
        self._proxy_model.setSourceModel(self._item_model)
        self._node_selector_view.setModel(self._proxy_model)
        self._filterkey_prev = ''

        # This 1 line is needed to enable horizontal scrollbar. This setting
        # isn't available in .ui file.
        # Ref. http://stackoverflow.com/a/6648906/577001
        self._node_selector_view.header().setResizeMode(
                                              0, QHeaderView.ResizeToContents)

        # Setting slot for when user clicks on QTreeView.
        self.selectionModel = self._node_selector_view.selectionModel()
        # Note: self.selectionModel.currentChanged doesn't work to deselect
        # a treenode as expected. Need to use selectionChanged.
        self.selectionModel.selectionChanged.connect(
                                                  self._selection_changed_slot)

    def node_deselected(self, grn):
        """
        Deselect the index that corresponds to the given GRN.

        :type grn: str
        """

        # Obtain the corresponding index.
        qindex_tobe_deselected = self._item_model.get_index_from_grn(grn)
        rospy.logdebug('NodeSelWidt node_deselected qindex={} data={}'.format(
                                qindex_tobe_deselected,
                                qindex_tobe_deselected.data(Qt.DisplayRole)))

        # Obtain all indices currently selected.
        indexes_selected = self.selectionModel.selectedIndexes()
        for index in indexes_selected:
            grn_from_selectedindex = RqtRosGraph.get_upper_grn(index, '')
            rospy.logdebug(' Compare given grn={} grn from selected={}'.format(
                                                  grn, grn_from_selectedindex))
            # If GRN retrieved from selected index matches the given one.
            if grn == grn_from_selectedindex:
                # Deselect the index.
                self.selectionModel.select(index, QItemSelectionModel.Deselect)

    def _selection_deselected(self, index_current, rosnode_name_selected):
        """
        Intended to be called from _selection_changed_slot.
        """
        self.selectionModel.select(index_current, QItemSelectionModel.Deselect)

        # Signal to notify other pane that also contains node widget.
        self.sig_node_selected.emit(rosnode_name_selected)

    def _selection_selected(self, index_current, rosnode_name_selected):
        """Intended to be called from _selection_changed_slot."""
        rospy.logdebug('_selection_changed_slot row={} col={} data={}'.format(
                          index_current.row(), index_current.column(),
                          index_current.data(Qt.DisplayRole)))

        # Determine if it's terminal treenode.
        found_node = False
        for nodeitem in self._nodeitems.itervalues():
            name_nodeitem = nodeitem.data(Qt.DisplayRole)
            name_rosnode_leaf = rosnode_name_selected[
                       rosnode_name_selected.rfind(RqtRosGraph.DELIM_GRN) + 1:]

            # If name of the leaf in the given name & the name taken from
            # nodeitem list matches.
            if ((name_nodeitem == rosnode_name_selected) and
                (name_nodeitem[name_nodeitem.rfind(RqtRosGraph.DELIM_GRN) + 1:]
                 == name_rosnode_leaf)):
                rospy.logdebug('terminal str {} MATCH {}'.format(
                                             name_nodeitem, name_rosnode_leaf))
                found_node = True
                break
        if not found_node:  # Only when it's NOT a terminal we deselect it.
            self.selectionModel.select(index_current,
                                       QItemSelectionModel.Deselect)
            return

        # Only when it's a terminal we move forward.
        item_child = self._item_model.itemFromIndex(index_current.child(0, 0))
        rospy.logdebug('item_selected={} item_child={} r={} c={}'.format(
                       index_current, item_child,
                       index_current.row(), index_current.column()))

        self.sig_node_selected.emit(rosnode_name_selected)

        # Show the node as selected.
        #selmodel.select(index_current, QItemSelectionModel.SelectCurrent)

    def _current_selection_changed_slot(self, qindex_curr, qindex_prev):

        # Obtaining the intended qindex is tricky. See  http://goo.gl/P6J5p
        # Here, instead of using Qt's standard way, I made a custom way to
        # get the corresponding qindex.

        rosnode_name_selected = RqtRosGraph.get_upper_grn(qindex_curr, '')
        rospy.loginfo(' index.data={} rosnode_name_selected={}'.format(
                      qindex_curr.data(Qt.DisplayRole),
                      rosnode_name_selected))
        if not rosnode_name_selected in self._nodeitems.keys():
            # De-select the selected item.
            self.selectionModel.select(qindex_curr,
                                       QItemSelectionModel.Deselect)
            return

        self._selection_selected(qindex_curr, rosnode_name_selected)

        #TODO: Detect deselection?
        #self._selection_deselected(qindex_curr, rosnode_name_selected)

    def _selection_changed_slot(self, selected, deselected):
        """
        Sends "open ROS Node box" signal ONLY IF the selected treenode is the
        terminal treenode.
        Receives args from signal QItemSelectionModel.selectionChanged.

        :param selected: All indexs where selected (could be multiple)
        :type selected: QItemSelection
        :type deselected: QItemSelection
        """

        ## Getting the index where user just selected. Should be single.
        if len(selected.indexes()) < 0 and len(deselected.indexes()) < 0:
            rospy.logerr('Nothing selected? Not ideal to reach here')
            return

        index_current = None
        if len(selected.indexes()) > 0:
            index_current = selected.indexes()[0]
        elif len(deselected.indexes()) == 1:
            # Setting length criteria as 1 is only a workaround, to avoid
            # Node boxes on right-hand side disappears when filter key doesn't
            # match them.
            # Indeed this workaround leaves another issue. Question for
            # permanent solution is asked here http://goo.gl/V4DT1
            index_current = deselected.indexes()[0]

        rosnode_name_selected = RqtRosGraph.get_upper_grn(index_current, '')

        # If retrieved node name isn't in the list of all nodes.
        if not rosnode_name_selected in self._nodeitems.keys():
            # De-select the selected item.
            self.selectionModel.select(index_current,
                                       QItemSelectionModel.Deselect)
            return

        if len(selected.indexes()) > 0:
            self._selection_selected(index_current, rosnode_name_selected)
        elif len(deselected.indexes()) > 0:
            self._selection_deselected(index_current, rosnode_name_selected)

    def get_paramitems(self):
        """
        :rtype: OrderedDict 1st elem is node's GRN name,
                2nd is TreenodeQstdItem instance
        """
        return self._nodeitems

    def _update_nodetree_pernode(self):
        """
        """

        # TODO(Isaac): 11/25/2012 dynamic_reconfigure only returns params that
        #             are associated with nodes. In order to handle independent
        #             params, different approach needs taken.
        try:
            nodes = dyn_reconf.find_reconfigure_services()
        except rosservice.ROSServiceIOException as e:
            rospy.logerr("Reconfigure GUI cannot connect to master.")
            raise e  # TODO Make sure 'raise' here returns or finalizes func.

        if not nodes == self._nodes_previous:
            i_node_curr = 1
            num_nodes = len(nodes)
            elapsedtime_overall = 0.0
            for node_name_grn in nodes:
                time_siglenode_loop = time.time()

                ####(Begin) For DEBUG ONLY; skip some dynreconf creation
#                if i_node_curr % 2 != 0:
#                    i_node_curr += 1
#                    continue
                #### (End) For DEBUG ONLY. ####

                treenodeitem_toplevel = TreenodeQstdItem(
                                 node_name_grn, TreenodeQstdItem.NODE_FULLPATH)
                _treenode_names = treenodeitem_toplevel.get_treenode_names()
                self._nodeitems[node_name_grn] = treenodeitem_toplevel
                self._add_children_treenode(treenodeitem_toplevel,
                                            self._rootitem, _treenode_names)

                time_siglenode_loop = time.time() - time_siglenode_loop
                elapsedtime_overall += time_siglenode_loop
                # NOT a debug print - please DO NOT remove. This print works
                # as progress notification when loading takes long time.
                rospy.loginfo('reconf ' +
                  'loading #{}/{} {} / {}sec node={}'.format(
                         i_node_curr, num_nodes, round(time_siglenode_loop, 2),
                         round(elapsedtime_overall, 2), node_name_grn))
                i_node_curr += 1

    def _add_children_treenode(self, treenodeitem_toplevel,
                               treenodeitem_parent, child_names_left):
        """
        Evaluate current treenode and the previous treenode at the same depth.
        If the name of both nodes is the same, current node instance is
        ignored (that means children will be added to the same parent). If not,
        the current node gets added to the same parent node. At the end, this
        function gets called recursively going 1 level deeper.

        :type treenodeitem_toplevel: TreenodeQstdItem
        :type treenodeitem_parent: TreenodeQstdItem.
        :type child_names_left: List of str
        :param child_names_left: List of strings that is sorted in hierarchical
                                 order of params.
        """
        # TODO(Isaac): Consider moving this method to rqt_py_common.

        name_currentnode = child_names_left.pop(0)
        grn_curr = treenodeitem_toplevel.get_raw_param_name()
        stditem_currentnode = TreenodeQstdItem(grn_curr,
                                               TreenodeQstdItem.NODE_FULLPATH)

        # item at the bottom is your most recent node.
        row_index_parent = treenodeitem_parent.rowCount() - 1

        # Obtain and instantiate prev node in the same depth.
        name_prev = ''
        stditem_prev = None
        if treenodeitem_parent.child(row_index_parent):
            stditem_prev = treenodeitem_parent.child(row_index_parent)
            name_prev = stditem_prev.text()

        stditem = None
        # If the name of both nodes is the same, current node instance is
        # ignored (that means children will be added to the same parent)
        if name_prev != name_currentnode:
            stditem_currentnode.setText(name_currentnode)
            treenodeitem_parent.appendRow(stditem_currentnode)
            stditem = stditem_currentnode
        else:
            stditem = stditem_prev

        if len(child_names_left) != 0:
            # TODO: View & Model are closely bound here. Ideally isolate those
            #       2. Maybe we should split into 2 class, 1 handles view,
            #       the other does model.
            self._add_children_treenode(treenodeitem_toplevel, stditem,
                                        child_names_left)
        else:  # Selectable ROS Node.
            #TODO: Accept even non-terminal treenode as long as it's ROS Node.
            self._item_model.set_item_from_index(grn_curr, stditem.index())

            try:
                stditem.connect_param_server()
            except rospy.exceptions.ROSException as e:
                rospy.logerr(e.message)
                #Remove item that fails to connect to its node from parent item
                treenodeitem_parent.takeRow(stditem.row())
                #TODO: Needs to show err msg on GUI too.

    def _refresh_nodes(self):
        # TODO: In the future, do NOT remove all nodes. Instead,
        #            remove only the ones that are gone. And add new ones too.

        model = self._rootitem
        if model.hasChildren():
            row_count = model.rowCount()
            model.removeRows(0, row_count)
            rospy.logdebug("ParamWidget _refresh_nodes row_count=%s",
                           row_count)
        self._update_nodetree_pernode()

    def close_node(self):
        rospy.logdebug(" in close_node")
        # TODO(Isaac) Figure out if dynamic_reconfigure needs to be closed.

    def set_filter(self, filter_):
        """
        Pass fileter instance to the child proxymodel.
        :type filter_: BaseFilter
        """
        self._proxy_model.set_filter(filter_)

    def _test_sel_index(self, selected, deselected):
        """
        Method for Debug only
        """
        #index_current = self.selectionModel.currentIndex()
        src_model = self._item_model
        index_current = None
        index_deselected = None
        index_parent = None
        curr_qstd_item = None
        if len(selected.indexes()) > 0:
            index_current = selected.indexes()[0]
            index_parent = index_current.parent()
            curr_qstd_item = src_model.itemFromIndex(index_current)
        elif len(deselected.indexes()) > 0:
            index_deselected = deselected.indexes()[0]
            index_parent = index_deselected.parent()
            curr_qstd_item = src_model.itemFromIndex(index_deselected)

        if len(selected.indexes()) > 0:
            rospy.logdebug('sel={} par={} desel={} sel.d={} par.d={}'.format(
                                 index_current, index_parent, index_deselected,
                                 index_current.data(Qt.DisplayRole),
                                 index_parent.data(Qt.DisplayRole),)
                                 + ' desel.d={} cur.item={}'.format(
                                 None,  # index_deselected.data(Qt.DisplayRole)
                                 curr_qstd_item))
        elif len(deselected.indexes()) > 0:
            rospy.logdebug('sel={} par={} desel={} sel.d={} par.d={}'.format(
                                 index_current, index_parent, index_deselected,
                                 None, index_parent.data(Qt.DisplayRole)) +
                           ' desel.d={} cur.item={}'.format(
                                 index_deselected.data(Qt.DisplayRole),
                                 curr_qstd_item))
