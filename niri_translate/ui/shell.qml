import QtQuick
import QtQuick.Controls
import QtQuick.Templates as T
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
    property string modelQuery: ""
    property string expandedModelId: ""
    property int modelScope: 0
    readonly property var visibleModels: (data.models || []).filter(function(model) {
        const query = modelQuery.trim().toLowerCase();
        const selected = model.id === ((data.models || [])[data.model] || {}).id;
        const inScope = modelScope === 0 ? (model.recommended || model.local_state === "present" || selected)
                      : modelScope === 1 ? true : model.local_state === "present";
        return model.kind === "translation" && inScope && (!query || [model.name, model.repo, model.description, model.quant].join(" ").toLowerCase().includes(query));
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
    readonly property color errorColor: theme.error || "#ba1a1a"
    readonly property color buttonFill: blend(card, ink, dark ? 0.045 : 0.025)
    readonly property color inputFill: blend(surface, dark ? "#000000" : "#ffffff", dark ? 0.12 : 0.5)
    readonly property color hoverFill: tint(accent, dark ? 0.14 : 0.08)
    readonly property color pressedFill: blend(card, ink, dark ? 0.14 : 0.09)
    readonly property color selectedFill: blend(card, accent, dark ? 0.10 : 0.045)

    function tint(color, alpha) {
        return Qt.rgba(color.r, color.g, color.b, alpha);
    }
    function blend(base, overlay, weight) {
        // Convert string literals through Qt so dark/light theme colors share one path.
        const over = Qt.tint("transparent", overlay);
        return Qt.rgba(base.r * (1 - weight) + over.r * weight,
                       base.g * (1 - weight) + over.g * weight,
                       base.b * (1 - weight) + over.b * weight, 1);
    }

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

    component UiLabel: Label {
        font.family: "sans-serif"
        font.pixelSize: 13
        color: shell.ink
        textFormat: Text.PlainText
    }

    // Shared controls avoid the default raised Material buttons and pill shapes.
    component ActionButton: T.Button {
        id: control
        property string variant: "secondary"
        property bool compact: false
        readonly property bool primary: variant === "primary"
        readonly property bool quiet: variant === "quiet"
        readonly property bool danger: variant === "danger"
        implicitWidth: Math.max(compact ? 56 : 76, contentItem.implicitWidth + leftPadding + rightPadding)
        implicitHeight: compact ? 30 : 36
        leftPadding: compact ? 10 : 14
        rightPadding: leftPadding
        topPadding: 6
        bottomPadding: 6
        font.family: "sans-serif"
        font.pixelSize: 13
        font.weight: primary ? Font.DemiBold : Font.Medium
        hoverEnabled: true
        focusPolicy: Qt.StrongFocus
        opacity: enabled ? 1 : 0.45
        contentItem: Text {
            text: control.text
            font: control.font
            color: control.primary ? shell.accentTextColor : control.danger ? shell.errorColor : control.quiet ? shell.muted : shell.ink
            horizontalAlignment: Text.AlignHCenter
            verticalAlignment: Text.AlignVCenter
            elide: Text.ElideRight
        }
        background: Rectangle {
            radius: 8
            color: control.primary ? (control.down ? Qt.darker(shell.accent, 1.12) : control.hovered ? Qt.darker(shell.accent, 1.05) : shell.accent)
                 : control.danger ? (control.hovered ? shell.tint(shell.errorColor, 0.12) : "transparent")
                 : control.down ? shell.pressedFill : control.hovered ? shell.hoverFill : control.quiet ? "transparent" : shell.buttonFill
            border.width: control.quiet || control.primary || control.danger ? 0 : 1
            border.color: control.hovered ? shell.line : shell.outline
            Behavior on color { ColorAnimation { duration: 110 } }
            Rectangle {
                anchors.fill: parent
                anchors.margins: -3
                visible: control.visualFocus
                radius: 11
                color: "transparent"
                border.width: 2
                border.color: shell.accent
            }
        }
        HoverHandler { cursorShape: control.enabled ? Qt.PointingHandCursor : Qt.ArrowCursor }
    }

    component QuietButton: ActionButton {
        variant: "quiet"
        compact: true
    }

    component SelectBox: T.ComboBox {
        id: select
        implicitHeight: 38
        implicitWidth: 220
        leftPadding: 12
        rightPadding: 34
        topPadding: 8
        bottomPadding: 8
        font.family: "sans-serif"
        font.pixelSize: 13
        hoverEnabled: true
        opacity: enabled ? 1 : 0.45
        contentItem: Text {
            text: select.displayText
            font: select.font
            color: shell.ink
            verticalAlignment: Text.AlignVCenter
            elide: Text.ElideRight
        }
        indicator: Canvas {
            x: select.width - width - 13
            y: (select.height - height) / 2
            width: 10
            height: 6
            property color strokeColor: shell.muted
            onStrokeColorChanged: requestPaint()
            onPaint: {
                const ctx = getContext("2d");
                ctx.clearRect(0, 0, width, height);
                ctx.strokeStyle = strokeColor;
                ctx.lineWidth = 1.5;
                ctx.lineCap = "round";
                ctx.lineJoin = "round";
                ctx.beginPath();
                ctx.moveTo(1, 1); ctx.lineTo(5, 5); ctx.lineTo(9, 1);
                ctx.stroke();
            }
        }
        background: Rectangle {
            radius: 8
            color: select.hovered ? shell.hoverFill : shell.inputFill
            border.width: 1
            border.color: select.visualFocus || select.popup.visible ? shell.accent : shell.outline
            Behavior on color { ColorAnimation { duration: 110 } }
        }
        delegate: T.ItemDelegate {
            id: option
            required property var modelData
            required property int index
            width: select.width - 12
            height: 36
            padding: 10
            highlighted: select.highlightedIndex === index
            hoverEnabled: true
            contentItem: Text {
                text: option.modelData
                font: select.font
                color: option.index === select.currentIndex ? shell.accent : shell.ink
                verticalAlignment: Text.AlignVCenter
            }
            background: Rectangle {
                radius: 6
                color: option.highlighted || option.hovered ? shell.hoverFill : "transparent"
            }
        }
        popup: T.Popup {
            y: select.height + 6
            width: select.width
            implicitHeight: Math.min(options.contentHeight + 12, 280)
            padding: 6
            closePolicy: T.Popup.CloseOnEscape | T.Popup.CloseOnPressOutside
            contentItem: ListView {
                id: options
                clip: true
                implicitHeight: contentHeight
                model: select.popup.visible ? select.delegateModel : null
                currentIndex: select.highlightedIndex
                highlightMoveDuration: 0
            }
            background: Rectangle {
                radius: 10
                color: shell.card
                border.width: 1
                border.color: shell.outline
            }
        }
    }

    component PathField: T.TextField {
        id: field
        clip: true
        implicitHeight: 40
        implicitWidth: 200
        leftPadding: 12
        rightPadding: 12
        topPadding: 9
        bottomPadding: 9
        font.family: "sans-serif"
        font.pixelSize: 13
        color: shell.ink
        placeholderTextColor: shell.muted
        selectionColor: shell.accent
        selectedTextColor: shell.accentTextColor
        opacity: enabled ? 1 : 0.5
        background: Rectangle {
            radius: 8
            color: shell.inputFill
            border.width: 1
            border.color: field.activeFocus ? shell.accent : shell.outline
            Behavior on border.color { ColorAnimation { duration: 110 } }
        }
    }

    component Toggle: T.Switch {
        id: toggle
        implicitWidth: contentItem.implicitWidth
        implicitHeight: 34
        spacing: 12
        padding: 0
        hoverEnabled: true
        opacity: enabled ? 1 : 0.45
        indicator: Rectangle {
            implicitWidth: 40
            implicitHeight: 24
            x: 0
            y: (toggle.height - height) / 2
            radius: 8
            color: toggle.checked ? shell.accent : shell.pressedFill
            border.width: toggle.visualFocus ? 2 : 1
            border.color: toggle.visualFocus ? shell.accent : toggle.checked ? shell.accent : shell.outline
            Rectangle {
                x: toggle.checked ? 20 : 4
                y: 4
                width: 16
                height: 16
                radius: 5
                color: toggle.checked ? shell.accentTextColor : shell.muted
                Behavior on x { NumberAnimation { duration: 130; easing.type: Easing.OutCubic } }
            }
            Behavior on color { ColorAnimation { duration: 130 } }
        }
        contentItem: Text {
            leftPadding: 52
            text: toggle.text
            font.family: "sans-serif"
            font.pixelSize: 13
            color: shell.ink
            verticalAlignment: Text.AlignVCenter
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
                radius: 18
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
                        UiLabel {
                            x: 48
                            y: 2
                            text: shell.data.settings ? "翻译设置" : "本地翻译"
                            font.pixelSize: 20
                            font.weight: Font.DemiBold
                            color: shell.ink
                        }
                        UiLabel {
                            x: 48
                            y: 32
                            text: shell.data.settings ? "管理模型与桌面偏好" : "Niri Translate · 离线翻译"
                            color: shell.muted
                            font.pixelSize: 12
                        }
                        Row {
                            anchors.right: parent.right
                            anchors.verticalCenter: parent.verticalCenter
                            QuietButton {
                                text: shell.data.settings ? "返回翻译" : "设置"
                                onClicked: shell.send("settings", !shell.data.settings)
                            }

                        }
                    }
                    Rectangle {
                        Layout.fillWidth: true
                        implicitHeight: 1
                        color: shell.outline
                    }
                    ColumnLayout {
                        visible: !shell.data.settings
                        Layout.fillHeight: true
                        Layout.fillWidth: true
                        spacing: 14
                        RowLayout {
                            SelectBox {
                                id: direction
                                Layout.preferredWidth: 220
                                model: ["英文 → 简体中文", "简体中文 → 英文"]
                                currentIndex: Number(shell.data.direction || 0)
                                onActivated: index => shell.send("direction", index)
                            }
                            ActionButton {
                                text: "⇄ 交换"
                                onClicked: shell.send("direction", 1 - shell.data.direction)
                            }
                            Item {
                                Layout.fillWidth: true
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
                                    UiLabel {
                                        text: "原文"
                                        font.bold: true
                                        color: shell.muted
                                    }
                                    Item {
                                        Layout.fillWidth: true
                                    }
                                    QuietButton {
                                        text: "清空"
                                        onClicked: source.clear()
                                    }
                                }
                                Rectangle {
                                    Layout.fillWidth: true
                                    Layout.fillHeight: true
                                    Layout.minimumWidth: 100
                                    radius: 12
                                    color: shell.inputFill
                                    border.width: 1
                                    border.color: source.activeFocus ? shell.accent : shell.outline
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
                                            font.family: "sans-serif"
                                            font.pixelSize: 15
                                            selectionColor: shell.accent
                                            selectedTextColor: shell.accentTextColor
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
                                    UiLabel {
                                        text: "译文"
                                        font.bold: true
                                        color: shell.muted
                                    }
                                    Item {
                                        Layout.fillWidth: true
                                    }
                                    QuietButton {
                                        text: "复制"
                                        enabled: result.length > 0
                                        onClicked: shell.send("copy")
                                    }
                                }
                                Rectangle {
                                    Layout.fillWidth: true
                                    Layout.fillHeight: true
                                    Layout.minimumWidth: 100
                                    radius: 12
                                    color: shell.card
                                    border.width: 1
                                    border.color: result.activeFocus ? shell.accent : shell.outline
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
                                            font.family: "sans-serif"
                                            font.pixelSize: 15
                                            selectionColor: shell.accent
                                            selectedTextColor: shell.accentTextColor
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
                            ActionButton {
                                id: translateButton
                                variant: "primary"
                                Layout.preferredWidth: 170
                                Layout.preferredHeight: 38
                                text: "翻译   Ctrl+Enter"
                                enabled: !!shell.data.ready
                                Accessible.name: "翻译，Ctrl+Enter"
                                onClicked: shell.send("translate")
                            }
                            ActionButton {
                                text: "停止"
                                enabled: !!shell.data.translating
                                onClicked: shell.send("stop")
                            }
                            Item {
                                Layout.fillWidth: true
                            }
                        }
                        UiLabel {
                            // Keep actionable errors and stop notices; omit idle copy and timing details.
                            readonly property string notice: shell.data.status || ""
                            text: shell.data.translating ? "正在翻译…" : notice
                            visible: !!shell.data.translating || (notice.length > 0
                                     && notice !== "内容仅在本机处理 · 不保存历史"
                                     && !notice.startsWith("完成 ·"))
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
                                radius: 12
                                color: shell.card
                                border.width: 1
                                border.color: shell.outline
                                ColumnLayout {
                                    id: computeBody
                                    anchors { left: parent.left; right: parent.right; top: parent.top; margins: 16 }
                                    spacing: 8
                                    RowLayout {
                                        Layout.fillWidth: true
                                        UiLabel { text: "计算设备"; font.pixelSize: 16; font.weight: Font.DemiBold; color: shell.ink }
                                        Item { Layout.fillWidth: true }
                                        SelectBox {
                                            Layout.preferredWidth: 220
                                            model: ["自动 · 优先使用 GPU", "仅使用 CPU"]
                                            currentIndex: shell.data.acceleration === "cpu" ? 1 : 0
                                            enabled: !shell.data.hardware_busy && !shell.data.model_busy
                                            onActivated: index => shell.send("acceleration", index === 1 ? "cpu" : "auto")
                                        }
                                    }
                                    UiLabel {
                                        Layout.fillWidth: true
                                        text: (shell.data.devices || []).length ? shell.data.devices.map(d => d.name + " · " + (d.memory_mib / 1024).toFixed(1) + " GiB 显存").join("\n") : (shell.data.hardware_detail || "正在检测…")
                                        wrapMode: Text.WrapAnywhere
                                        color: shell.ink
                                    }
                                    UiLabel {
                                        Layout.fillWidth: true
                                        text: "当前运行：" + (shell.data.backend || "尚未加载") + "\n自动模式在 GPU 不可用或加载失败时回退 CPU；切换模式会重新加载模型。"
                                        color: shell.muted; wrapMode: Text.WordWrap; font.pixelSize: 12
                                    }
                                }
                            }
                            Rectangle {
                                Layout.fillWidth: true
                                implicitHeight: storageBody.implicitHeight + 32
                                radius: 12
                                color: shell.card
                                border.width: 1
                                border.color: shell.outline
                                ColumnLayout {
                                    id: storageBody
                                    anchors { left: parent.left; right: parent.right; top: parent.top; margins: 16 }
                                    spacing: 8
                                    UiLabel { text: "模型存储位置"; font.pixelSize: 16; font.weight: Font.DemiBold; color: shell.ink }
                                    PathField {
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
                                        ActionButton {
                                            text: "选择文件夹…"
                                            enabled: directoryInput.enabled
                                            onClicked: {
                                                folderPicker.currentFolder = shell.data.models_dir_url || "";
                                                folderPicker.open();
                                            }
                                        }
                                        ActionButton {
                                            variant: "primary"
                                            text: "应用目录"
                                            enabled: directoryInput.enabled && shell.directoryDraft.trim().length > 0 && shell.directoryDraft !== shell.savedDirectory
                                            onClicked: shell.send("models_dir", shell.directoryDraft)
                                        }
                                        QuietButton { text: "打开当前目录"; onClicked: shell.send("open_storage") }
                                        QuietButton {
                                            text: "恢复默认"
                                            enabled: directoryInput.enabled && (!shell.data.models_dir_default || shell.directoryDraft !== shell.savedDirectory)
                                            onClicked: shell.send("reset_models_dir")
                                        }
                                    }
                                    UiLabel {
                                        Layout.fillWidth: true
                                        text: (shell.data.models_dir_default ? "跟随系统默认：" : "自定义目录：") + (shell.data.models_dir || "")
                                        color: shell.muted; font.pixelSize: 12; wrapMode: Text.WrapAnywhere
                                    }
                                    UiLabel {
                                        Layout.fillWidth: true
                                        text: "默认目录由当前用户的系统数据目录决定。应用目录或恢复默认会重新加载模型，中断当前翻译；已有模型和下载片段不会搬移。"
                                        color: shell.muted; font.pixelSize: 12; wrapMode: Text.WordWrap
                                    }
                                    UiLabel {
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
                                UiLabel { text: "翻译模型库"; font.pixelSize: 16; font.weight: Font.DemiBold; color: shell.ink }
                                Item { Layout.fillWidth: true }
                                QuietButton { text: "扫描本地"; onClicked: shell.send("refresh_models") }
                                ActionButton {
                                    text: shell.data.catalog_busy ? "更新中…" : "在线更新"
                                    enabled: !shell.data.catalog_busy
                                    onClicked: shell.send("refresh_catalog")
                                }
                                QuietButton { visible: !!shell.data.catalog_busy; text: "取消"; onClicked: shell.send("cancel_catalog") }
                            }
                            RowLayout {
                                Layout.fillWidth: true
                                spacing: 10
                                PathField {
                                    Layout.fillWidth: true
                                    placeholderText: "搜索翻译模型或量化，例如 1.8B / 4B / Q4"
                                    text: shell.modelQuery
                                    onTextEdited: shell.modelQuery = text
                                    selectByMouse: true
                                }
                                SelectBox {
                                    Layout.preferredWidth: 148
                                    model: ["常用小模型", "全部模型", "已在本地"]
                                    currentIndex: shell.modelScope
                                    onActivated: index => shell.modelScope = index
                                }
                            }
                            UiLabel {
                                Layout.fillWidth: true
                                text: "显示 " + shell.visibleModels.length + " / " + shell.data.models.length + " 个选项 · 默认推荐轻量翻译模型。全部模型中可选择较大的 7B；点击下载才会获取权重。"
                                color: shell.muted; wrapMode: Text.WordWrap; font.pixelSize: 12
                            }
                            UiLabel {
                                Layout.fillWidth: true
                                text: (shell.data.catalog_status || "") + (shell.data.catalog_updated ? "\n最近更新：" + new Date(shell.data.catalog_updated).toLocaleString() : "")
                                color: shell.data.catalog_error ? shell.errorColor : shell.muted
                                wrapMode: Text.WordWrap; font.pixelSize: 12
                            }
                            UiLabel {
                                visible: shell.visibleModels.length === 0
                                Layout.fillWidth: true
                                text: "没有匹配的模型，可清空搜索或切换到全部模型。"
                                color: shell.muted; wrapMode: Text.WordWrap
                            }
                            Repeater {
                                model: shell.visibleModels
                                delegate: Rectangle {
                                    id: modelCard
                                    required property var modelData
                                    required property int index
                                    readonly property bool detailsExpanded: shell.expandedModelId === modelData.id
                                    readonly property bool selected: modelData.id === (shell.data.models[shell.data.model] || {}).id
                                    readonly property bool present: modelData.local_state === "present"
                                    Layout.fillWidth: true
                                    implicitHeight: modelBody.implicitHeight + 20
                                    radius: 8
                                    color: selected ? shell.selectedFill : shell.card
                                    border.color: selected ? shell.tint(shell.accent, 0.6) : shell.outline
                                    border.width: 1
                                    ColumnLayout {
                                        id: modelBody
                                        anchors { left: parent.left; right: parent.right; top: parent.top; margins: 10 }
                                        spacing: 5
                                        RowLayout {
                                            Layout.fillWidth: true
                                            UiLabel {
                                                Layout.fillWidth: true
                                                text: modelCard.modelData.name
                                                font.pixelSize: 14; font.weight: Font.DemiBold; color: shell.ink; wrapMode: Text.WordWrap
                                            }
                                            Rectangle {
                                                implicitWidth: modelBadge.implicitWidth + 12
                                                implicitHeight: 20
                                                radius: 6
                                                color: modelCard.present ? shell.tint(shell.accent, 0.09) : shell.buttonFill
                                                UiLabel {
                                                    id: modelBadge
                                                    anchors.centerIn: parent
                                                    text: modelCard.selected && shell.data.ready ? "运行中" : modelCard.modelData.label
                                                    color: modelCard.present ? shell.accent : shell.muted
                                                    font.pixelSize: 11
                                                }
                                            }
                                        }
                                        UiLabel {
                                            Layout.fillWidth: true
                                            text: (modelCard.modelData.size / 1e9).toFixed(2) + " GB  ·  " + modelCard.modelData.description + (modelCard.modelData.external ? "  ·  外部文件" : "")
                                            color: shell.muted; font.pixelSize: 12; elide: Text.ElideRight
                                        }
                                        UiLabel {
                                            visible: modelCard.detailsExpanded
                                            Layout.fillWidth: true
                                            text: modelCard.modelData.publisher + " · " + modelCard.modelData.repo
                                            color: shell.muted; font.pixelSize: 11; wrapMode: Text.WrapAnywhere
                                        }
                                        TextEdit {
                                            visible: modelCard.detailsExpanded
                                            Layout.fillWidth: true
                                            text: modelCard.modelData.path
                                            readOnly: true; selectByMouse: true; textFormat: TextEdit.PlainText
                                            color: shell.muted; font.family: "sans-serif"; font.pixelSize: 12; wrapMode: TextEdit.WrapAnywhere
                                            selectionColor: shell.accent; selectedTextColor: shell.accentTextColor
                                        }
                                        UiLabel {
                                            visible: modelCard.modelData.partial_size > 0
                                            text: "已下载 " + (modelCard.modelData.partial_size / 1e9).toFixed(2) + " / " + (modelCard.modelData.size / 1e9).toFixed(2) + " GB，可继续下载"
                                            color: shell.muted; font.pixelSize: 12
                                        }
                                        RowLayout {
                                            Layout.fillWidth: true
                                            ActionButton {
                                                compact: true
                                                variant: modelCard.selected && shell.data.ready ? "secondary" : "primary"
                                                text: modelCard.selected && shell.data.model_busy ? "处理中…" : modelCard.selected && shell.data.loading ? "加载中…" : modelCard.selected && shell.data.ready ? "重新加载" : modelCard.present ? "使用此模型" : modelCard.modelData.local_state === "partial" ? "继续下载" : modelCard.modelData.local_state === "invalid" ? "重新下载" : "下载模型"
                                                enabled: !shell.data.model_busy && !shell.data.hardware_busy && !shell.data.loading
                                                onClicked: shell.send(modelCard.present ? "model_load" : "model_download", modelCard.modelData.id)
                                            }
                                            QuietButton {
                                                text: modelCard.detailsExpanded ? "收起详情" : "详情"
                                                onClicked: shell.expandedModelId = modelCard.detailsExpanded ? "" : modelCard.modelData.id
                                            }
                                            QuietButton { visible: modelCard.detailsExpanded; text: "打开目录"; onClicked: shell.send("open_folder", modelCard.modelData.id) }
                                            QuietButton { visible: modelCard.detailsExpanded; text: "复制路径"; onClicked: shell.send("copy_path", modelCard.modelData.id) }
                                            QuietButton { visible: modelCard.detailsExpanded; text: "模型来源"; onClicked: shell.send("model_source", modelCard.modelData.id) }
                                            Item { Layout.fillWidth: true }
                                            QuietButton {
                                                visible: modelCard.selected && (shell.data.model_busy || shell.data.loading)
                                                text: "取消"; onClicked: shell.send("cancel_model")
                                            }
                                        }
                                        T.ProgressBar {
                                            id: downloadProgress
                                            visible: modelCard.selected && shell.data.model_busy
                                            Layout.fillWidth: true
                                            implicitHeight: 4
                                            from: 0; to: 100; value: Number(shell.data.progress || 0)
                                            background: Rectangle { radius: 2; color: shell.pressedFill }
                                            contentItem: Item {
                                                Rectangle {
                                                    width: parent.width * downloadProgress.position
                                                    height: parent.height
                                                    radius: 2
                                                    color: shell.accent
                                                }
                                            }
                                        }
                                        UiLabel {
                                            visible: modelCard.selected && shell.data.model_busy
                                            Layout.fillWidth: true
                                            text: (shell.data.model_status || "") + " · " + Number(shell.data.progress || 0).toFixed(1) + "%"
                                            color: shell.muted; font.pixelSize: 12; wrapMode: Text.WordWrap
                                        }
                                    }
                                }
                            }
                            RowLayout {
                                ActionButton { text: "导入本地 GGUF…"; enabled: !shell.data.model_busy && !shell.data.hardware_busy; onClicked: filePicker.open() }
                                UiLabel { Layout.fillWidth: true; text: "直接使用原文件，不复制；按模型库中的完整校验值识别。"; color: shell.muted; font.pixelSize: 12; wrapMode: Text.WordWrap }
                            }
                            Rectangle { Layout.fillWidth: true; implicitHeight: 1; color: shell.outline }
                            UiLabel { text: "桌面与窗口"; font.pixelSize: 16; font.weight: Font.DemiBold; color: shell.ink }
                            Toggle {
                                text: "登录后自动启动到托盘"
                                checked: !!shell.data.autostart
                                onClicked: shell.send("autostart", checked)
                            }
                            UiLabel { text: "抽屉宽度 · " + shell.data.width + " px"; color: shell.muted }
                            T.Slider {
                                id: widthSlider
                                Layout.fillWidth: true
                                implicitHeight: 28
                                leftPadding: 8; rightPadding: 8
                                from: 640; to: 1200; stepSize: 20
                                value: Number(shell.data.width || 820)
                                onMoved: shell.send("width", value)
                                background: Rectangle {
                                    x: widthSlider.leftPadding
                                    y: (widthSlider.height - height) / 2
                                    width: widthSlider.availableWidth
                                    height: 4
                                    radius: 2
                                    color: shell.pressedFill
                                    Rectangle { width: parent.width * widthSlider.position; height: 4; radius: 2; color: shell.accent }
                                }
                                handle: Rectangle {
                                    x: widthSlider.leftPadding + widthSlider.visualPosition * (widthSlider.availableWidth - width)
                                    y: (widthSlider.height - height) / 2
                                    implicitWidth: 16; implicitHeight: 20
                                    radius: 5
                                    color: shell.accent
                                    border.width: widthSlider.visualFocus ? 2 : 0
                                    border.color: shell.accentTextColor
                                }
                            }
                            UiLabel {
                                Layout.fillWidth: true
                                text: "拖动左边缘也可调整宽度。点击外部或按 Esc 收起。\n收起保留文字，退出后清空；不保存翻译历史。"
                                color: shell.muted; font.pixelSize: 12; wrapMode: Text.WordWrap
                            }
                            ActionButton { variant: "danger"; text: "退出客户端"; onClicked: shell.send("quit") }
                            UiLabel {
                                text: shell.data.status || ""; Layout.fillWidth: true
                                wrapMode: Text.WordWrap; color: shell.muted; font.pixelSize: 12
                            }
                        }
                    }
                    Rectangle {
                        visible: !!shell.data.settings
                        Layout.fillWidth: true
                        implicitHeight: footer.implicitHeight + 20
                        radius: 8
                        color: shell.selectedFill
                        border.width: 1
                        border.color: shell.outline
                        RowLayout {
                            id: footer
                            anchors.fill: parent
                            anchors.margins: 10
                            spacing: 10
                            Rectangle {
                                implicitWidth: 7
                                implicitHeight: 7
                                radius: 4
                                color: shell.data.ready ? shell.accent : (shell.theme.error || shell.muted)
                            }
                            UiLabel {
                                Layout.fillWidth: true
                                text: ((shell.data.models[shell.data.model] || {}).name || "本地模型") + " · " + (shell.data.model_status || "")
                                wrapMode: Text.WordWrap
                                color: shell.muted
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
            title: "选择模型库中的 GGUF"
            nameFilters: ["GGUF 模型 (*.gguf)"]
            onAccepted: shell.send("local", selectedFile.toString())
        }
    }
}
