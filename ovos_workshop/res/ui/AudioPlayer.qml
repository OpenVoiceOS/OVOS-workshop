/*
    * Copyright 2020 by Aditya Mehra <aix.m@outlook.com>
    *
    * Licensed under the Apache License, Version 2.0 (the "License");
    * you may not use this file except in compliance with the License.
    * You may obtain a copy of the License at
    *
    *    http://www.apache.org/licenses/LICENSE-2.0
    *
    * Unless required by applicable law or agreed to in writing, software
    * distributed under the License is distributed on an "AS IS" BASIS,
    * WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
    * See the License for the specific language governing permissions and
    * limitations under the License.
    *
    */

import QtQuick 2.12
import QtMultimedia 5.12
import QtQuick.Controls 2.12 as Controls
import QtQuick.Templates 2.12 as T
import QtQuick.Layouts 1.3
import org.kde.kirigami 2.8 as Kirigami
import QtGraphicalEffects 1.0
import Mycroft 1.0 as Mycroft

Mycroft.Delegate {
    id: root
    skillBackgroundSource: media.bg_image
    property alias thumbnail: albumimg.source
    fillWidth: true
    property int imageWidth: Kirigami.Units.gridUnit * 10
    skillBackgroundColorOverlay: Qt.rgba(0, 0, 0, 0.85)
    property bool bigMode: width > 800 && height > 600 ? 1 : 0
    property bool horizontalMode: width >= height * 1.3 ? 1 : 0
    property bool isVertical: sessionData.isVertical

    // Assumption Track_Length is always in milliseconds
    // Assumption current_Position is always in milleseconds and relative to track_length if track_length = 530000, position values range from 0 to 530000

    property var media: sessionData.media
    property var compareModel
    property var playerDuration: media.length
    property real playerPosition: 0
    property var playerState: media.status
    property var nextAction: "next"
    property var previousAction: "previous"
    property var seekAction: "seek"
    property var pauseAction: "pause"
    property var resumeAction: "resume"
    property var positionFromMetadata: media.position

    onPositionFromMetadataChanged: {
        playerPosition = media.position
        playerState = "Playing"
    }

    onIsVerticalChanged: {
        if(isVertical){
            root.horizontalMode = false
        }
    }

    function formatedDuration(millis){
        var minutes = Math.floor(millis / 60000);
        var seconds = ((millis % 60000) / 1000).toFixed(0);
        return minutes + ":" + (seconds < 10 ? '0' : '') + seconds;
    }

    Controls.ButtonGroup {
        id: autoPlayRepeatGroup
        buttons: autoPlayRepeatGroupLayout.children
    }
    
    onPlayerStateChanged: {
        console.log(playerState)
    }

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: bigMode ? parent.width * 0.025 : 0

        Rectangle {
            Layout.fillWidth: true
            Layout.minimumHeight: songtitle.contentHeight
            color: "transparent"

            Kirigami.Heading {
                id: songtitle
                text: media.title
                level: 1
                maximumLineCount: 1
                width: parent.width
                font.pixelSize: parent.width * 0.060
                horizontalAlignment: Text.AlignHCenter
                verticalAlignment: Text.AlignVCenter
                elide: Text.ElideRight
                font.capitalization: Font.Capitalize
                font.bold: true
                visible: true
                enabled: true
            }
        }

        Rectangle {
            Layout.fillWidth: true
            Layout.fillHeight: true
            color: "transparent"

            GridLayout {
                id: mainLayout
                anchors.fill: parent
                columns: horizontalMode ? 2 : 1

                Rectangle {
                    Layout.fillWidth: true
                    Layout.preferredHeight: mainLayout.columns > 1 ? parent.height : parent.height / 1.5
                    color: "transparent"

                    Image {
                        id: albumimg
                        visible: true
                        enabled: true
                        width: parent.height * 0.9
                        height: width
                        source: media.image
                        anchors.verticalCenter: parent.verticalCenter
                        anchors.horizontalCenter: parent.horizontalCenter
                        z: 100
                    }


                    RectangularGlow {
                        id: effect
                        anchors.fill: albumimg
                        glowRadius: 5
                        color: Qt.rgba(0, 0, 0, 0.7)
                        cornerRadius: 10
                    }
                }

                ColumnLayout {
                    Layout.fillWidth: true
                    Layout.fillHeight: true

                    Rectangle {
                        Layout.fillWidth: true
                        Layout.fillHeight: true
                        color: "transparent"

                        RowLayout {
                            anchors.fill: parent
                            anchors.margins: horizontalMode ? Kirigami.Units.largeSpacing : Kirigami.Units.largeSpacing * 2
                            spacing: horizontalMode ? Kirigami.Units.largeSpacing * 3 : Kirigami.Units.largeSpacing * 5

                            Controls.Button {
                                id: previousButton
                                Layout.fillWidth: true
                                Layout.fillHeight: true
                                Layout.alignment: Qt.AlignVCenter
                                focus: false
                                KeyNavigation.right: playButton
                                KeyNavigation.down: seekableslider
                                onClicked: {
                                    triggerGuiEvent(previousAction, {})
                                }

                                contentItem: Kirigami.Icon {
                                    source: Qt.resolvedUrl("images/media-seek-backward.svg")
                                }

                                background: Rectangle {
                                    color: "transparent"
                                }

                                Keys.onReturnPressed: {
                                    clicked()
                                }
                            }

                            Controls.Button {
                                id: playButton
                                Layout.fillWidth: true
                                Layout.fillHeight: true
                                Layout.alignment: Qt.AlignVCenter
                                onClicked: {
                                    if (playerState === "Paused"){
                                        console.log("in resume action")
                                        triggerGuiEvent(resumeAction, {"media": {
                                                                "image": media.image,
                                                                "track": media.track,
                                                                "album": media.album,
                                                                "skill": media.skill,
                                                                "length": media.length,
                                                                "position": playerPosition,
                                                                "status": "Playing"}})
                                    } else {
                                        console.log("in pause action")
                                        triggerGuiEvent(pauseAction, {"media": {
                                                                "image": media.image,
                                                                "title": media.title,
                                                                "album": media.album,
                                                                "skill_id":media.skill,
                                                                "length": media.length,
                                                                "position": playerPosition,
                                                                "status": "Paused"}})
                                    }
                                }

                                background: Rectangle {
                                    color: "transparent"
                                }

                                contentItem: Kirigami.Icon {
                                    source: playerState === "Playing" ? Qt.resolvedUrl("images/media-playback-pause.svg") : Qt.resolvedUrl("images/media-playback-start.svg")
                                }
                            }

                            Controls.Button {
                                id: nextButton
                                Layout.fillWidth: true
                                Layout.fillHeight: true
                                Layout.alignment: Qt.AlignVCenter
                                onClicked: {
                                    triggerGuiEvent(nextAction, {})
                                }

                                background: Rectangle {
                                    color: "transparent"
                                }

                                contentItem: Kirigami.Icon {
                                    source: Qt.resolvedUrl("images/media-seek-forward.svg")
                                }
                            }
                        }
                    }
                }
            }
        }

        T.Slider {
            id: seekableslider
            to: playerDuration
            Layout.fillWidth: true
            Layout.minimumHeight: Kirigami.Units.gridUnit * 2
            Layout.leftMargin: Kirigami.Units.largeSpacing
            Layout.rightMargin: Kirigami.Units.largeSpacing
            Layout.bottomMargin: Kirigami.Units.largeSpacing
            Layout.topMargin: Kirigami.Units.smallSpacing
            property bool sync: false
            live: false
            visible: media.length !== -1 ? 1 : 0
            enabled: media.length !== -1 ? 1 : 0
            value: playerPosition

            onPressedChanged: {
                triggerGuiEvent(seekAction, {"seekValue": value})
            }

            handle: Item {
                x: seekableslider.visualPosition * (parent.width - (Kirigami.Units.largeSpacing + Kirigami.Units.smallSpacing))
                anchors.verticalCenter: parent.verticalCenter
                height: Kirigami.Units.iconSizes.large

                Rectangle {
                    id: hand
                    anchors.verticalCenter: parent.verticalCenter
                    implicitWidth: Kirigami.Units.iconSizes.small + Kirigami.Units.smallSpacing
                    implicitHeight: Kirigami.Units.iconSizes.small + Kirigami.Units.smallSpacing
                    radius: 100
                    color: seekableslider.pressed ? "#f0f0f0" : "#f6f6f6"
                    border.color: "#bdbebf"
                }

                Controls.Label {
                    anchors.bottom: parent.bottom
                    anchors.bottomMargin: -Kirigami.Units.smallSpacing
                    anchors.horizontalCenter: hand.horizontalCenter
                    //horizontalAlignment: Text.AlignHCenter
                    text: formatedDuration(playerPosition)
                }
            }

            background: Rectangle {
                x: seekableslider.leftPadding
                y: seekableslider.topPadding + seekableslider.availableHeight / 2 - height / 2
                implicitHeight: 10
                width: seekableslider.availableWidth
                height: implicitHeight + Kirigami.Units.largeSpacing
                radius: 10
                color: "#bdbebf"

                Rectangle {
                    width: seekableslider.visualPosition * parent.width
                    height: parent.height
                    gradient: Gradient {
                        orientation: Gradient.Horizontal
                        GradientStop { position: 0.0; color: "#21bea6" }
                        GradientStop { position: 1.0; color: "#2194be" }
                    }
                    radius: 9
                }
            }
        }
    }
}
