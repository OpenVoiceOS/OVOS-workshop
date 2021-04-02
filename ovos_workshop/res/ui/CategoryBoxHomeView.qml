/*
 *  Copyright 2020 by Aditya Mehra <aix.m@outlook.com>
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
    property var videosHomeListModel: sessionData.videosHomeModel

    Layout.fillWidth: true
    Layout.fillHeight: true
    
    onFocusChanged: {
        if(focus){
            videosListView.forceActiveFocus()
        }
    }
    
    onVideosHomeListModelChanged: {
        videosListView.forceLayout()
    }
    
    Item {
        id: videosContainer
        anchors.fill: parent
        anchors.leftMargin: Kirigami.Units.gridUnit
        anchors.rightMargin: Kirigami.Units.gridUnit
            
        Kirigami.CardsGridView {
            id: videosListView
            anchors.fill: parent
            anchors.leftMargin: Kirigami.Units.largeSpacing + Kirigami.Units.smallSpacing
            cellHeight: cellWidth * 0.5625 + Kirigami.Units.gridUnit * 2.5
            displayMarginBeginning: 125
            displayMarginEnd: 125
            focus: false
            model: videosHomeListModel
            delegate: Delegates.GridVideoCard{}
        }
    }
}
