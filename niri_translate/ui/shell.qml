import QtQuick
import QtQuick.Controls
import QtQuick.Controls.Material
import QtQuick.Layouts
import QtQuick.Dialogs
import Quickshell
import Quickshell.Io
import Quickshell.Wayland

ShellRoot {
    id: shell
    property var data: ({
            open: false,
            settings: false,
            source: "",
            output: "",
            direction: 0,
            model: 0,
            width: 820,
            status: "正在连接本地服务…",
            model_status: "",
            ready: false,
            translating: false,
            model_busy: false,
            progress: 0,
            autostart: false,
            models: []
        })
    property bool applying: false
    property bool sourcePending: false
    property string lastSentSource: ""
    readonly property var theme: data.theme || ({})
    readonly property color surface: theme.surface || "#f3f9fc"
    readonly property color card: theme.card || "#f0f4f7"
    readonly property color ink: theme.ink || "#171c1f"
    readonly property color muted: theme.muted || "#40484c"
    readonly property color accent: theme.accent || "#08677f"
    readonly property color accentTextColor: theme.on_accent || "#ffffff"
    readonly property color line: theme.line || "#bfc8cc"
    readonly property color outline: theme.border || "#dde5e9"
    readonly property color footerColor: theme.footer || "#b8eaff"
    readonly property color footerText: theme.footer_text || "#001f28"
    readonly property bool dark: !!theme.dark

    function send(cmd, value) {
        if (channel.connected) {
            channel.write(JSON.stringify({
                cmd: cmd,
                value: value
            }) + "\n");
            channel.flush();
        }
    }
    function accept(text) {
        try {
            const next = JSON.parse(text);
            applying = true;
            data = next;
            if (!sourcePending || next.source === lastSentSource) {
                sourcePending = false;
                if (source.text !== next.source)
                    source.text = next.source;
            }
            if (result.text !== next.output) {
                if (next.output.startsWith(result.text))
                    result.insert(result.length, next.output.slice(result.length));
                else
                    result.text = next.output;
            }
            applying = false;
        } catch (error) {
            applying = false;
        }
    }

    Socket {
        id: channel
        path: Quickshell.env("NIRI_TRANSLATE_SOCKET")
        connected: true
        parser: SplitParser {
            onRead: text => shell.accept(text)
        }
        onConnectionStateChanged: {
            if (!connected)
                reconnect.start();
        }
    }
    Timer {
        id: reconnect
        interval: 1000
        onTriggered: channel.connected = true
    }
    IpcHandler {
        target: "drawer"
        function show(): void {
            shell.send("show");
        }
        function hide(): void {
            shell.send("hide");
        }
        function toggle(): void {
            shell.send("toggle");
        }
        function status(): string {
            return JSON.stringify({
                connected: channel.connected,
                visible: window.visible,
                open: !!shell.data.open,
                settings: !!shell.data.settings,
                width: panel.width,
                sourceLength: source.length,
                outputLength: result.length,
                ready: !!shell.data.ready,
                dark: shell.dark,
                surface: shell.surface.toString(),
                ink: shell.ink.toString(),
                accentTextColor: shell.accentTextColor.toString(),
                namespace: "niri-translate-drawer"
            });
        }
        function capture(path: string): void {
            panel.grabToImage(image => image.saveToFile(path));
        }
    }

    PanelWindow {
        id: window
        visible: !!shell.data.open || slide.running
        screen: Quickshell.screens[0]
        color: "transparent"
        exclusiveZone: 0
        anchors {
            top: true
            bottom: true
            left: true
            right: true
        }
        WlrLayershell.layer: WlrLayer.Top
        WlrLayershell.namespace: "niri-translate-drawer"
        WlrLayershell.exclusionMode: ExclusionMode.Normal
        WlrLayershell.keyboardFocus: shell.data.open ? WlrKeyboardFocus.Exclusive : WlrKeyboardFocus.None
        Material.theme: shell.dark ? Material.Dark : Material.Light
        Material.accent: shell.accent
        Material.primary: shell.surface
        Material.background: shell.surface
        Material.foreground: shell.ink

        onVisibleChanged: if (visible)
            Qt.callLater(() => gateway.forceActiveFocus())
        Shortcut {
            sequence: "Escape"
            enabled: window.visible
            onActivated: shell.send("hide")
        }
        Shortcut {
            sequence: "Ctrl+Return"
            enabled: window.visible && !shell.data.settings
            onActivated: shell.send("translate")
        }
        Shortcut {
            sequence: "Ctrl+Enter"
            enabled: window.visible && !shell.data.settings
            onActivated: shell.send("translate")
        }
        FocusScope {
            id: gateway
            anchors.fill: parent
            focus: true
            MouseArea {
                anchors.fill: parent
                onClicked: shell.send("hide")
            }
            Rectangle {
                id: panel
                Material.theme: shell.dark ? Material.Dark : Material.Light
                Material.accent: shell.accent
                Material.primary: shell.surface
                Material.foreground: shell.ink
                Material.background: shell.surface
                width: Math.min(Number(shell.data.width || 820), window.width - 32)
                height: Math.max(320, window.height - 32)
                y: 16
                x: shell.data.open ? window.width - width - 16 : window.width + 4
                radius: 24
                color: Qt.rgba(shell.surface.r, shell.surface.g, shell.surface.b, Number(shell.theme.opacity === undefined ? 1 : shell.theme.opacity))
                border.width: 1
                border.color: shell.outline
                clip: true
                Behavior on x {
                    NumberAnimation {
                        id: slide
                        duration: 220
                        easing.type: Easing.OutCubic
                    }
                }
                MouseArea {
                    anchors.fill: parent
                    onClicked: mouse => mouse.accepted = true
                }
                MouseArea {
                    width: 10
                    height: parent.height
                    z: 5
                    cursorShape: Qt.SizeHorCursor
                    property real startX: 0
                    property real startWidth: 0
                    onPressed: mouse => {
                        startX = mapToItem(gateway, mouse.x, mouse.y).x;
                        startWidth = panel.width;
                    }
                    onPositionChanged: mouse => {
                        if (pressed)
                            shell.send("width", Math.round(startWidth + startX - mapToItem(gateway, mouse.x, mouse.y).x));
                    }
                }
                ColumnLayout {
                    anchors.fill: parent
                    anchors.margins: 24
                    spacing: 16
                    Item {
                        Layout.fillWidth: true
                        Layout.minimumHeight: 52
                        Layout.maximumHeight: 52
                        Layout.preferredHeight: 52
                        Image {
                            anchors.left: parent.left
                            anchors.verticalCenter: parent.verticalCenter
                            width: 36
                            height: 36
                            source: Quickshell.env("NIRI_TRANSLATE_ICON")
                            sourceSize.width: 36
                            sourceSize.height: 36
                        }
                        Label {
                            x: 48
                            y: 2
                            text: shell.data.settings ? "翻译设置" : "本地翻译"
                            font.pixelSize: 22
                            font.bold: true
                            color: shell.ink
                        }
                        Label {
                            x: 48
                            y: 32
                            text: "Niri Translate"
                            color: shell.muted
                            font.pixelSize: 12
                        }
                        Row {
                            anchors.right: parent.right
                            anchors.verticalCenter: parent.verticalCenter
                            ToolButton {
                                text: shell.data.settings ? "返回" : "设置"
                                onClicked: shell.send("settings", !shell.data.settings)
                            }
                            ToolButton {
                                text: "⋯"
                                Accessible.name: "更多操作"
                                onClicked: more.open()
                                Menu {
                                    id: more
                                    MenuItem {
                                        text: "退出客户端"
                                        onTriggered: shell.send("quit")
                                    }
                                }
                            }
                            ToolButton {
                                text: "✕"
                                Accessible.name: "收起抽屉"
                                onClicked: shell.send("hide")
                            }
                        }
                    }
                    Rectangle {
                        Layout.fillWidth: true
                        implicitHeight: 1
                        color: shell.line
                    }
                    ColumnLayout {
                        visible: !shell.data.settings
                        Layout.fillHeight: true
                        Layout.fillWidth: true
                        spacing: 14
                        RowLayout {
                            ComboBox {
                                id: direction
                                Layout.preferredWidth: 220
                                model: ["英文 → 简体中文", "简体中文 → 英文"]
                                currentIndex: Number(shell.data.direction || 0)
                                onActivated: index => shell.send("direction", index)
                            }
                            Button {
                                text: "⇄ 交换"
                                onClicked: shell.send("direction", 1 - shell.data.direction)
                            }
                            Item {
                                Layout.fillWidth: true
                            }
                            Label {
                                text: "仅在本机处理"
                                color: shell.muted
                                font.pixelSize: 12
                            }
                        }
                        RowLayout {
                            Layout.fillWidth: true
                            Layout.fillHeight: true
                            spacing: 14
                            ColumnLayout {
                                Layout.fillWidth: true
                                Layout.fillHeight: true
                                RowLayout {
                                    Label {
                                        text: "原文"
                                        font.bold: true
                                        color: shell.muted
                                    }
                                    Item {
                                        Layout.fillWidth: true
                                    }
                                    ToolButton {
                                        text: "清空"
                                        onClicked: source.clear()
                                    }
                                }
                                Rectangle {
                                    Layout.fillWidth: true
                                    Layout.fillHeight: true
                                    Layout.minimumWidth: 100
                                    radius: 14
                                    color: shell.card
                                    ScrollView {
                                        id: sourceScroll
                                        contentWidth: availableWidth
                                        contentHeight: source.height
                                        anchors.fill: parent
                                        anchors.margins: 4
                                        clip: true
                                        TextArea {
                                            id: source
                                            width: sourceScroll.availableWidth
                                            height: Math.max(sourceScroll.availableHeight, contentHeight + topPadding + bottomPadding)
                                            placeholderText: ""
                                            textFormat: TextEdit.PlainText
                                            wrapMode: TextEdit.Wrap
                                            selectByMouse: true
                                            color: shell.ink
                                            placeholderTextColor: shell.muted
                                            font.pixelSize: 16
                                            topPadding: 14
                                            bottomPadding: 14
                                            leftPadding: 14
                                            rightPadding: 14
                                            background: null
                                            Text {
                                                x: 14
                                                y: 14
                                                width: parent.width - 28
                                                text: "输入或粘贴原文…\n\nCtrl+Enter 开始翻译"
                                                visible: source.length === 0
                                                color: shell.muted
                                                font: source.font
                                                wrapMode: Text.WordWrap
                                            }
                                            onTextChanged: {
                                                if (!shell.applying) {
                                                    shell.sourcePending = true;
                                                    shell.lastSentSource = text;
                                                    shell.send("source", text);
                                                }
                                            }
                                        }
                                    }
                                }
                            }
                            ColumnLayout {
                                Layout.fillWidth: true
                                Layout.fillHeight: true
                                RowLayout {
                                    Label {
                                        text: "译文"
                                        font.bold: true
                                        color: shell.muted
                                    }
                                    Item {
                                        Layout.fillWidth: true
                                    }
                                    ToolButton {
                                        text: "复制"
                                        enabled: result.length > 0
                                        onClicked: shell.send("copy")
                                    }
                                }
                                Rectangle {
                                    Layout.fillWidth: true
                                    Layout.fillHeight: true
                                    Layout.minimumWidth: 100
                                    radius: 14
                                    color: shell.card
                                    ScrollView {
                                        id: resultScroll
                                        contentWidth: availableWidth
                                        contentHeight: result.height
                                        anchors.fill: parent
                                        anchors.margins: 4
                                        clip: true
                                        TextArea {
                                            id: result
                                            width: resultScroll.availableWidth
                                            height: Math.max(resultScroll.availableHeight, contentHeight + topPadding + bottomPadding)
                                            readOnly: true
                                            selectByMouse: true
                                            placeholderText: ""
                                            textFormat: TextEdit.PlainText
                                            wrapMode: TextEdit.Wrap
                                            color: shell.ink
                                            placeholderTextColor: shell.muted
                                            font.pixelSize: 16
                                            topPadding: 14
                                            bottomPadding: 14
                                            leftPadding: 14
                                            rightPadding: 14
                                            background: null
                                            Text {
                                                x: 14
                                                y: 14
                                                width: parent.width - 28
                                                text: "译文会在这里逐步显示"
                                                visible: result.length === 0
                                                color: shell.muted
                                                font: result.font
                                                wrapMode: Text.WordWrap
                                            }
                                        }
                                    }
                                }
                            }
                        }
                        RowLayout {
                            Rectangle {
                                id: translateButton
                                Layout.preferredWidth: 164
                                Layout.preferredHeight: 42
                                radius: 21
                                color: shell.data.ready ? shell.accent : shell.card
                                activeFocusOnTab: !!shell.data.ready
                                Accessible.role: Accessible.Button
                                Accessible.name: "翻译，Ctrl+Enter"
                                Accessible.onPressAction: if (shell.data.ready)
                                    shell.send("translate")
                                Keys.onReturnPressed: if (shell.data.ready)
                                    shell.send("translate")
                                Keys.onSpacePressed: if (shell.data.ready)
                                    shell.send("translate")
                                Text {
                                    anchors.centerIn: parent
                                    text: "翻译  Ctrl+Enter"
                                    font.pixelSize: 14
                                    color: shell.data.ready ? shell.accentTextColor : shell.muted
                                }
                                MouseArea {
                                    anchors.fill: parent
                                    enabled: !!shell.data.ready
                                    cursorShape: Qt.PointingHandCursor
                                    onClicked: shell.send("translate")
                                }
                            }
                            Button {
                                text: "停止"
                                enabled: !!shell.data.translating
                                onClicked: shell.send("stop")
                            }
                            Item {
                                Layout.fillWidth: true
                            }
                            Label {
                                text: "Esc 收起"
                                color: shell.muted
                                font.pixelSize: 12
                            }
                        }
                        Label {
                            text: shell.data.status || ""
                            Layout.fillWidth: true
                            wrapMode: Text.WordWrap
                            color: shell.muted
                            font.pixelSize: 13
                        }
                    }
                    ScrollView {
                        visible: !!shell.data.settings
                        Layout.fillHeight: true
                        Layout.fillWidth: true
                        clip: true
                        contentWidth: availableWidth
                        ColumnLayout {
                            width: parent.width
                            spacing: 18
                            Label {
                                text: "翻译模型"
                                font.pixelSize: 18
                                font.bold: true
                            }
                            ComboBox {
                                Layout.fillWidth: true
                                model: shell.data.models.map(m => m.name + " · " + (m.size / 1e9).toFixed(2) + " GB")
                                currentIndex: Number(shell.data.model || 0)
                                onActivated: index => shell.send("model", index)
                            }
                            Label {
                                text: "模型按需下载，同一时间只运行一个。文件大小不等于运行内存。"
                                Layout.fillWidth: true
                                wrapMode: Text.WordWrap
                                color: shell.muted
                            }
                            ProgressBar {
                                visible: !!shell.data.model_busy
                                Layout.fillWidth: true
                                from: 0
                                to: 100
                                value: Number(shell.data.progress || 0)
                            }
                            Label {
                                visible: !!shell.data.model_busy
                                text: Number(shell.data.progress || 0).toFixed(1) + "%"
                                color: shell.muted
                            }
                            RowLayout {
                                Button {
                                    text: "下载所选模型"
                                    enabled: !shell.data.model_busy
                                    onClicked: shell.send("download")
                                }
                                Button {
                                    text: "加载 / 重试"
                                    enabled: !shell.data.model_busy
                                    onClicked: shell.send("load")
                                }
                                Button {
                                    text: "取消"
                                    onClicked: shell.send("cancel_model")
                                }
                            }
                            Button {
                                text: "选择本地 GGUF…"
                                enabled: !shell.data.model_busy
                                onClicked: filePicker.open()
                            }
                            Label {
                                text: "仅支持列表中的三个官方文件，加载前校验 SHA-256。\n不自动下载模型；模型就绪后无需联网。"
                                Layout.fillWidth: true
                                wrapMode: Text.WordWrap
                                color: shell.muted
                            }
                            Rectangle {
                                Layout.fillWidth: true
                                implicitHeight: 1
                                color: shell.line
                            }
                            Label {
                                text: "桌面行为"
                                font.pixelSize: 18
                                font.bold: true
                            }
                            Switch {
                                text: "登录桌面后自动启动（仅显示托盘）"
                                checked: !!shell.data.autostart
                                onClicked: shell.send("autostart", checked)
                            }
                            Label {
                                text: "抽屉宽度 · " + shell.data.width + " px"
                                color: shell.muted
                            }
                            Slider {
                                Layout.fillWidth: true
                                from: 640
                                to: 1200
                                stepSize: 20
                                value: Number(shell.data.width || 820)
                                onMoved: shell.send("width", value)
                            }
                            Label {
                                text: "也可以拖动抽屉左侧边缘调整宽度。\n关闭抽屉会保留文字；退出客户端后清空，不保存翻译历史。"
                                Layout.fillWidth: true
                                wrapMode: Text.WordWrap
                                color: shell.muted
                            }
                            Label {
                                text: shell.data.status || ""
                                Layout.fillWidth: true
                                wrapMode: Text.WordWrap
                                color: shell.muted
                            }
                        }
                    }
                    Rectangle {
                        Layout.fillWidth: true
                        implicitHeight: footer.implicitHeight + 24
                        radius: 12
                        color: shell.footerColor
                        RowLayout {
                            id: footer
                            anchors.fill: parent
                            anchors.margins: 12
                            spacing: 10
                            Rectangle {
                                implicitWidth: 7
                                implicitHeight: 7
                                radius: 4
                                color: shell.data.ready ? shell.accent : (shell.theme.error || shell.muted)
                            }
                            Label {
                                Layout.fillWidth: true
                                text: ((shell.data.models[shell.data.model] || {}).name || "本地模型") + " · " + (shell.data.model_status || "")
                                wrapMode: Text.WordWrap
                                color: shell.footerText
                                font.pixelSize: 12
                            }
                        }
                    }
                }
            }
        }
        FileDialog {
            id: filePicker
            title: "选择受支持的官方 GGUF"
            nameFilters: ["GGUF 模型 (*.gguf)"]
            onAccepted: shell.send("local", selectedFile.toString())
        }
    }
}
