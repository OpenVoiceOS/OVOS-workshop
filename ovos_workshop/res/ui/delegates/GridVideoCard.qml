import QtQuick 2.9
import QtQuick.Layouts 1.4
import QtGraphicalEffects 1.0
import QtQuick.Controls 2.3
import org.kde.kirigami 2.8 as Kirigami
import Mycroft 1.0 as Mycroft

ItemDelegate {
    id: delegate
    
    readonly property bool isCurrent: {
        videosListView.currentIndex == index && activeFocus && !videosListView
        .moving
    }

    property int borderSize: Kirigami.Units.smallSpacing
    property int baseRadius: 3

    z: isCurrent ? 2 : 0
    
    leftPadding: Kirigami.Units.largeSpacing * 2
    topPadding: Kirigami.Units.largeSpacing * 2
    rightPadding: Kirigami.Units.largeSpacing * 2
    bottomPadding: Kirigami.Units.largeSpacing * 2

    leftInset: Kirigami.Units.largeSpacing
    topInset: Kirigami.Units.largeSpacing
    rightInset: Kirigami.Units.largeSpacing
    bottomInset: Kirigami.Units.largeSpacing
    
    implicitHeight: videosListView.cellHeight
    
    background: Item {
        id: background
        
        Rectangle {
            id: frame
            anchors.fill: parent
            color: Kirigami.Theme.backgroundColor
            radius: delegate.baseRadius
            border.width: delegate.activeFocus ? 4 : 0
            border.color: delegate.activeFocus ? Kirigami.Theme.linkColor : "transparent"
            layer.enabled: true
            layer.effect: DropShadow {
                transparentBorder: false
                horizontalOffset: 2
                verticalOffset: 2
            }
        }
    }
    
    contentItem: ColumnLayout {
        spacing: Kirigami.Units.smallSpacing

        Item {
            id: imgRoot
            Layout.alignment: Qt.AlignTop
            Layout.fillWidth: true
            Layout.topMargin: -delegate.topPadding + delegate.topInset + extraBorder
            Layout.leftMargin: -delegate.leftPadding + delegate.leftInset + extraBorder
            Layout.rightMargin: -delegate.rightPadding + delegate.rightInset + extraBorder
            Layout.preferredHeight: width * 0.5625 + delegate.baseRadius
            property real extraBorder: 0

            layer.enabled: true
            layer.effect: OpacityMask {
                maskSource: Rectangle {
                    x: imgRoot.x;
                    y: imgRoot.y
                    width: imgRoot.width
                    height: imgRoot.height
                    radius: delegate.baseRadius
                }
            }

            Image {
                id: img
                source: model.logo ? model.logo : "https://uroehr.de/vtube/view/img/video-placeholder.png"
                anchors {
                    fill: parent
                    // To not round under
                    bottomMargin: delegate.baseRadius
                }
                opacity: 1
                fillMode: Image.PreserveAspectCrop
            }
            
            states: [
                State {
                    when: delegate.isCurrent
                    PropertyChanges {
                        target: imgRoot
                        extraBorder: delegate.borderSize
                    }
                },
                State {
                    when: !delegate.isCurrent
                    PropertyChanges {
                        target: imgRoot
                        extraBorder: 0
                    }
                }
            ]
            transitions: Transition {
                onRunningChanged: {
                    // Optimize when animating the thumbnail
                    img.smooth = !running
                }
                NumberAnimation {
                    property: "extraBorder"
                    duration: Kirigami.Units.longDuration
                    easing.type: Easing.InOutQuad
                }
            }
        }

        Kirigami.Heading {
            id: videoLabel
            Layout.fillWidth: true
            Layout.alignment: Qt.AlignLeft | Qt.AlignTop
            wrapMode: Text.Wrap
            level: 3
            maximumLineCount: 1
            elide: Text.ElideRight
            color: Kirigami.Theme.textColor
            Component.onCompleted: {
                text = model.title
            }
        }
    }
    
    Keys.onReturnPressed: {
        clicked()
    }

    onClicked: {
        videosListView.forceActiveFocus()
        videosListView.currentIndex = index
        busyIndicatorPop.open()
        if(model.identifier != "showmore") {
            triggerGuiEvent("ovos_utils.play_event",
            {"modelData": {"title": model.title, "url": model.url,
            "lang": model.lang, "logo": model.logo, "tags": model.tags,
            "identifier": model.identifier, "skill_id": model.skill}})
        }
    }
}
