/*
 *  Copyright 2018 by Aditya Mehra <aix.m@outlook.com>
 *
 *  This program is free software: you can redistribute it and/or modify
 *  it under the terms of the GNU General Public License as published by
 *  the Free Software Foundation, either version 3 of the License, or
 *  (at your option) any later version.

 *  This program is distributed in the hope that it will be useful,
 *  but WITHOUT ANY WARRANTY; without even the implied warranty of
 *  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
 *  GNU General Public License for more details.

 *  You should have received a copy of the GNU General Public License
 *  along with this program.  If not, see <http://www.gnu.org/licenses/>.
 */

import QtQuick 2.9
import QtQuick.Layouts 1.4
import QtGraphicalEffects 1.0
import QtQuick.Controls 2.3
import org.kde.kirigami 2.8 as Kirigami
import Mycroft 1.0 as Mycroft
import "views" as Views
import "delegates" as Delegates

Item {
    property var historyListModel: sessionData.historyModel
    Layout.fillWidth: true
    Layout.fillHeight: true
    readonly property int responsiveCellWidth: width >= 600 ? parent.width / 5 : parent.width / 2
    
    onFocusChanged: {
        if(focus){
            historyGridView.forceActiveFocus()
        }
    }
    
    onHistoryListModelChanged: {
        historyGridView.view.forceLayout()
    }

    Views.GridTileView {
        id: historyGridView
        anchors {
            top: parent.top
            left: parent.left
            right: parent.right
            bottom: parent.bottom
        }
        focus: true
        model: historyListModel
        title: count > 0 ? "Watch History" : "No Recent History"

        cellWidth: responsiveCellWidth 
        cellHeight: cellWidth / 1.8 + Kirigami.Units.gridUnit * 5
        delegate: Delegates.ListVideoCard {
            width: historyGridView.cellWidth
            height: historyGridView.cellHeight
        }
        KeyNavigation.up: historyCatButton
    }
}
