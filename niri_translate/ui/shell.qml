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
    property string directoryDraft: ""
    property string savedDirectory: ""
    property int directoryRevision: -1
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
            if (savedDirectory !== next.models_dir || directoryRevision !== Number(next.storage_revision || 0)) {
                directoryRevision = Number(next.storage_revision || 0);
                savedDirectory = next.models_dir || "";
                directoryDraft = savedDirectory;
            }
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
                                        ScrollBar.vertical: ScrollBar { policy: ScrollBar.AlwaysOff }
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
                                        ScrollBar.vertical: ScrollBar { policy: ScrollBar.AlwaysOff }
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
                        id: settingsScroll
                        visible: !!shell.data.settings
                        Layout.fillHeight: true
                        Layout.fillWidth: true
                        clip: true
                        contentWidth: availableWidth
                        ScrollBar.vertical: ScrollBar { policy: ScrollBar.AlwaysOff }
                        ColumnLayout {
                            width: settingsScroll.availableWidth
                            spacing: 16
                            Rectangle {
                                Layout.fillWidth: true
                                implicitHeight: computeBody.implicitHeight + 32
                                radius: 16
                                color: shell.card
                                ColumnLayout {
                                    id: computeBody
                                    anchors { left: parent.left; right: parent.right; top: parent.top; margins: 16 }
                                    spacing: 8
                                    RowLayout {
                                        Layout.fillWidth: true
                                        Label { text: "计算设备"; font.pixelSize: 18; font.bold: true; color: shell.ink }
                                        Item { Layout.fillWidth: true }
                                        ComboBox {
                                            Layout.preferredWidth: 220
                                            model: ["自动 · 优先使用 GPU", "仅使用 CPU"]
                                            currentIndex: shell.data.acceleration === "cpu" ? 1 : 0
                                            enabled: !shell.data.hardware_busy && !shell.data.model_busy
                                            onActivated: index => shell.send("acceleration", index === 1 ? "cpu" : "auto")
                                        }
                                    }
                                    Label {
                                        Layout.fillWidth: true
                                        text: (shell.data.devices || []).length ? shell.data.devices.map(d => d.name + " · " + (d.memory_mib / 1024).toFixed(1) + " GiB 显存").join("\n") : (shell.data.hardware_detail || "正在检测…")
                                        wrapMode: Text.WrapAnywhere
                                        color: shell.ink
                                    }
                                    Label {
                                        Layout.fillWidth: true
                                        text: "当前运行：" + (shell.data.backend || "尚未加载") + "\n自动模式在 GPU 不可用或加载失败时回退 CPU；切换模式会重新加载模型。"
                                        color: shell.muted; wrapMode: Text.WordWrap; font.pixelSize: 12
                                    }
                                }
                            }
                            Rectangle {
                                Layout.fillWidth: true
                                implicitHeight: storageBody.implicitHeight + 32
                                radius: 16
                                color: shell.card
                                ColumnLayout {
                                    id: storageBody
                                    anchors { left: parent.left; right: parent.right; top: parent.top; margins: 16 }
                                    spacing: 8
                                    Label { text: "模型存储位置"; font.pixelSize: 18; font.bold: true; color: shell.ink }
                                    TextField {
                                        id: directoryInput
                                        Layout.fillWidth: true
                                        text: shell.directoryDraft
                                        placeholderText: "填写绝对路径，或点击选择文件夹"
                                        selectByMouse: true
                                        enabled: !shell.data.model_busy && !shell.data.loading && !shell.data.hardware_busy
                                        onTextEdited: shell.directoryDraft = text
                                        onAccepted: if (enabled && text.trim()) shell.send("models_dir", text)
                                    }
                                    Flow {
                                        Layout.fillWidth: true
                                        spacing: 8
                                        Button {
                                            text: "选择文件夹…"
                                            enabled: directoryInput.enabled
                                            onClicked: {
                                                folderPicker.currentFolder = shell.data.models_dir_url || "";
                                                folderPicker.open();
                                            }
                                        }
                                        Button {
                                            text: "应用目录"
                                            enabled: directoryInput.enabled && shell.directoryDraft.trim().length > 0 && shell.directoryDraft !== shell.savedDirectory
                                            onClicked: shell.send("models_dir", shell.directoryDraft)
                                        }
                                        ToolButton { text: "打开当前目录"; onClicked: shell.send("open_storage") }
                                        ToolButton {
                                            text: "恢复默认"
                                            enabled: directoryInput.enabled
                                            onClicked: shell.directoryDraft = shell.data.default_models_dir
                                        }
                                    }
                                    Label {
                                        Layout.fillWidth: true
                                        text: "当前目录：" + (shell.data.models_dir || "")
                                        color: shell.muted; font.pixelSize: 12; wrapMode: Text.WrapAnywhere
                                    }
                                    Label {
                                        Layout.fillWidth: true
                                        text: "应用后会重新扫描并加载模型，中断正在进行的翻译。已有模型和下载片段不会搬移；可导入旧目录的模型，或切回旧目录继续下载。"
                                        color: shell.muted; font.pixelSize: 12; wrapMode: Text.WordWrap
                                    }
                                    Label {
                                        visible: !!shell.data.storage_status
                                        Layout.fillWidth: true
                                        text: shell.data.storage_status || ""
                                        color: shell.data.storage_error ? (shell.theme.error || shell.muted) : shell.accent
                                        font.pixelSize: 12; wrapMode: Text.WordWrap
                                    }
                                }
                            }
                            RowLayout {
                                Layout.fillWidth: true
                                Label { text: "模型管理"; font.pixelSize: 18; font.bold: true; color: shell.ink }
                                Item { Layout.fillWidth: true }
                                ToolButton { text: "刷新本地状态"; onClicked: shell.send("refresh_models") }
                            }
                            Label {
                                Layout.fillWidth: true
                                text: "按需下载，一次运行一个模型。已有文件在加载前会校验完整性。"
                                color: shell.muted; wrapMode: Text.WordWrap; font.pixelSize: 12
                            }
                            Repeater {
                                model: shell.data.models
                                delegate: Rectangle {
                                    id: modelCard
                                    required property var modelData
                                    required property int index
                                    readonly property bool selected: index === shell.data.model
                                    readonly property bool present: modelData.local_state === "present"
                                    Layout.fillWidth: true
                                    implicitHeight: modelBody.implicitHeight + 28
                                    radius: 14
                                    color: shell.card
                                    border.color: selected ? shell.accent : shell.outline
                                    border.width: selected ? 2 : 1
                                    ColumnLayout {
                                        id: modelBody
                                        anchors { left: parent.left; right: parent.right; top: parent.top; margins: 14 }
                                        spacing: 5
                                        RowLayout {
                                            Layout.fillWidth: true
                                            Label {
                                                Layout.fillWidth: true
                                                text: modelCard.modelData.name
                                                font.bold: true; color: shell.ink; wrapMode: Text.WordWrap
                                            }
                                            Label {
                                                text: modelCard.selected && shell.data.ready ? "运行中" : modelCard.modelData.label
                                                color: modelCard.present ? shell.accent : shell.muted
                                                font.pixelSize: 12
                                            }
                                        }
                                        Label {
                                            Layout.fillWidth: true
                                            text: (modelCard.modelData.size / 1e9).toFixed(2) + " GB  ·  " + (["推荐日常使用 · 速度与体积均衡", "更高量化精度 · 占用更多内存", "更大模型 · 占用更多内存和显存"][modelCard.index]) + (modelCard.modelData.external ? "  ·  外部文件" : "")
                                            color: shell.muted; font.pixelSize: 12; wrapMode: Text.WordWrap
                                        }
                                        TextEdit {
                                            Layout.fillWidth: true
                                            text: modelCard.modelData.path
                                            readOnly: true; selectByMouse: true; textFormat: TextEdit.PlainText
                                            color: shell.muted; font.pixelSize: 11; wrapMode: TextEdit.WrapAnywhere
                                        }
                                        Label {
                                            visible: modelCard.modelData.partial_size > 0
                                            text: "已下载 " + (modelCard.modelData.partial_size / 1e9).toFixed(2) + " / " + (modelCard.modelData.size / 1e9).toFixed(2) + " GB，可继续下载"
                                            color: shell.muted; font.pixelSize: 12
                                        }
                                        RowLayout {
                                            Layout.fillWidth: true
                                            Button {
                                                text: modelCard.selected && shell.data.model_busy ? "处理中…" : modelCard.selected && shell.data.loading ? "加载中…" : modelCard.selected && shell.data.ready ? "重新加载" : modelCard.present ? "使用此模型" : modelCard.modelData.local_state === "partial" ? "继续下载" : modelCard.modelData.local_state === "invalid" ? "重新下载" : "下载模型"
                                                enabled: !shell.data.model_busy && !shell.data.hardware_busy && !shell.data.loading
                                                onClicked: shell.send(modelCard.present ? "model_load" : "model_download", modelCard.index)
                                            }
                                            ToolButton { text: "打开目录"; onClicked: shell.send("open_folder", modelCard.index) }
                                            ToolButton { text: "复制路径"; onClicked: shell.send("copy_path", modelCard.index) }
                                            Item { Layout.fillWidth: true }
                                            ToolButton {
                                                visible: modelCard.selected && (shell.data.model_busy || shell.data.loading)
                                                text: "取消"; onClicked: shell.send("cancel_model")
                                            }
                                        }
                                        ProgressBar {
                                            visible: modelCard.selected && shell.data.model_busy
                                            Layout.fillWidth: true; from: 0; to: 100; value: Number(shell.data.progress || 0)
                                        }
                                        Label {
                                            visible: modelCard.selected && shell.data.model_busy
                                            Layout.fillWidth: true
                                            text: (shell.data.model_status || "") + " · " + Number(shell.data.progress || 0).toFixed(1) + "%"
                                            color: shell.muted; font.pixelSize: 12; wrapMode: Text.WordWrap
                                        }
                                    }
                                }
                            }
                            RowLayout {
                                Button { text: "导入本地 GGUF…"; enabled: !shell.data.model_busy && !shell.data.hardware_busy; onClicked: filePicker.open() }
                                Label { Layout.fillWidth: true; text: "直接使用原文件，不复制；支持上方三个官方模型。"; color: shell.muted; font.pixelSize: 12; wrapMode: Text.WordWrap }
                            }
                            Rectangle { Layout.fillWidth: true; implicitHeight: 1; color: shell.outline }
                            Label { text: "桌面与窗口"; font.pixelSize: 18; font.bold: true; color: shell.ink }
                            Switch {
                                text: "登录后自动启动到托盘"
                                checked: !!shell.data.autostart
                                onClicked: shell.send("autostart", checked)
                            }
                            Label { text: "抽屉宽度 · " + shell.data.width + " px"; color: shell.muted }
                            Slider {
                                Layout.fillWidth: true; from: 640; to: 1200; stepSize: 20
                                value: Number(shell.data.width || 820)
                                onMoved: shell.send("width", value)
                            }
                            Label {
                                Layout.fillWidth: true
                                text: "拖动左边缘也可调整宽度。点击外部或按 Esc 收起。\n收起保留文字，退出后清空；不保存翻译历史。"
                                color: shell.muted; font.pixelSize: 12; wrapMode: Text.WordWrap
                            }
                            Button { text: "退出客户端"; onClicked: shell.send("quit") }
                            Label {
                                text: shell.data.status || ""; Layout.fillWidth: true
                                wrapMode: Text.WordWrap; color: shell.muted; font.pixelSize: 12
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
        FolderDialog {
            id: folderPicker
            title: "选择模型存储目录"
            onAccepted: shell.directoryDraft = decodeURIComponent(selectedFolder.toString().replace(/^file:\/\//, ""))
        }
        FileDialog {
            id: filePicker
            title: "选择受支持的官方 GGUF"
            nameFilters: ["GGUF 模型 (*.gguf)"]
            onAccepted: shell.send("local", selectedFile.toString())
        }
    }
}
