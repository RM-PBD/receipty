(function () {
    const openedAsFile = window.location.protocol === "file:";
    if (openedAsFile) {
        document.getElementById("launchWarning").hidden = false;
    }

    const dropZone = document.getElementById("dropZone");
    const fileInput = document.getElementById("fileInput");
    const fileList = document.getElementById("fileList");
    const goButton = document.getElementById("goButton");
    const clearBtn = document.getElementById("clearBtn");
    const actions = document.getElementById("actions");
    const resultsSummary = document.getElementById("resultsSummary");
    const sourceDirInput = document.getElementById("sourceDir");
    const outputDirInput = document.getElementById("outputDir");
    const outputRow = document.querySelector(".output-row");
    const toggles = document.querySelectorAll(".toggle");
    const browseSource = document.getElementById("browseSource");
    const browseOutput = document.getElementById("browseOutput");

    const ACCEPTED_TYPES = new Set([
        "image/jpeg", "image/png", "image/webp", "application/pdf",
    ]);
    const ACCEPTED_EXTS = new Set([".jpg", ".jpeg", ".png", ".webp", ".pdf"]);
    const CONCURRENCY = 3;

    let files = [];
    let previews = new Map();
    let mode = "rename";
    let phase = "select";
    let processing = false;
    let dragCounter = 0;

    async function pickFolder(prompt) {
        if (openedAsFile) return null;
        const response = await fetch("/api/pick-folder", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ prompt }),
        });
        const data = await response.json();
        return data.path;
    }

    browseSource.addEventListener("click", async () => {
        const path = await pickFolder("Select your receipt folder");
        if (path) {
            sourceDirInput.value = path;
            invalidatePreview();
        }
    });

    browseOutput.addEventListener("click", async () => {
        const path = await pickFolder("Select output folder");
        if (path) {
            outputDirInput.value = path;
            invalidatePreview();
        }
    });

    toggles.forEach((button) => {
        button.addEventListener("click", () => {
            if (processing || button.dataset.mode === mode) return;
            toggles.forEach((item) => item.classList.remove("active"));
            button.classList.add("active");
            mode = button.dataset.mode;
            outputRow.classList.toggle("hidden", mode !== "copy");
            invalidatePreview();
        });
    });

    dropZone.addEventListener("dragenter", (event) => {
        event.preventDefault();
        dragCounter += 1;
        dropZone.classList.add("drag-over");
    });
    dropZone.addEventListener("dragover", (event) => event.preventDefault());
    dropZone.addEventListener("dragleave", () => {
        dragCounter -= 1;
        if (dragCounter === 0) dropZone.classList.remove("drag-over");
    });
    dropZone.addEventListener("drop", (event) => {
        event.preventDefault();
        dragCounter = 0;
        dropZone.classList.remove("drag-over");
        if (!processing) addFiles(event.dataTransfer.files);
    });
    dropZone.addEventListener("click", () => {
        if (!processing) fileInput.click();
    });
    fileInput.addEventListener("change", () => {
        addFiles(fileInput.files);
        fileInput.value = "";
    });

    function isAccepted(file) {
        if (ACCEPTED_TYPES.has(file.type)) return true;
        const extension = "." + file.name.split(".").pop().toLowerCase();
        return ACCEPTED_EXTS.has(extension);
    }

    function addFiles(newFiles) {
        const existing = new Set(files.map((file) => file.name));
        Array.from(newFiles).filter(isAccepted).forEach((file) => {
            if (!existing.has(file.name)) {
                files.push(file);
                existing.add(file.name);
            }
        });
        if (files.length === 0) return;
        invalidatePreview();
        renderFileList();
        actions.hidden = false;
    }

    function renderFileList() {
        fileList.hidden = files.length === 0;
        fileList.innerHTML = files.map((file, index) => `
            <div class="file-item" data-index="${index}" id="file-${index}">
                <span class="file-icon">${file.name.toLowerCase().endsWith(".pdf") ? "&#128196;" : "&#128247;"}</span>
                <span class="file-name">${escapeHtml(file.name)}</span>
                <span class="file-status" id="status-${index}">Ready</span>
                <button class="file-remove" data-index="${index}" aria-label="Remove ${escapeHtml(file.name)}">&times;</button>
            </div>`).join("");

        fileList.querySelectorAll(".file-remove").forEach((button) => {
            button.addEventListener("click", (event) => {
                event.stopPropagation();
                if (processing) return;
                files.splice(Number(button.dataset.index), 1);
                invalidatePreview();
                renderFileList();
                if (files.length === 0) actions.hidden = true;
            });
        });
    }

    function invalidatePreview() {
        if (processing) return;
        previews = new Map();
        phase = "select";
        goButton.textContent = "Preview names";
        goButton.disabled = false;
        resultsSummary.hidden = true;
        if (files.length && fileList.children.length) renderFileList();
    }

    clearBtn.addEventListener("click", () => {
        if (processing) return;
        files = [];
        previews = new Map();
        phase = "select";
        fileList.innerHTML = "";
        fileList.hidden = true;
        actions.hidden = true;
        resultsSummary.hidden = true;
        goButton.textContent = "Preview names";
    });

    goButton.addEventListener("click", async () => {
        if (openedAsFile) {
            document.getElementById("launchWarning").scrollIntoView({ behavior: "smooth" });
            return;
        }
        if (files.length === 0 || processing) return;
        if (!validateFolders()) return;

        processing = true;
        goButton.disabled = true;
        fileList.querySelectorAll(".file-remove").forEach((button) => (button.hidden = true));

        if (phase === "select") {
            goButton.textContent = "Reading receipts...";
            const results = await previewFiles();
            showPreviewSummary(results);
            const readyCount = results.filter((result) => result.status === "success").length;
            phase = readyCount ? "previewed" : "select";
            goButton.textContent = readyCount ? `Apply ${readyCount} change${readyCount === 1 ? "" : "s"}` : "Preview names";
        } else if (phase === "previewed") {
            goButton.textContent = "Applying changes...";
            const results = await applyFiles();
            showApplySummary(results);
            phase = "done";
            goButton.textContent = "Changes applied";
        }

        processing = false;
        goButton.disabled = phase === "done";
    });

    function validateFolders() {
        if (!sourceDirInput.value.trim()) {
            flagInvalid(sourceDirInput);
            return false;
        }
        if (mode === "copy" && !outputDirInput.value.trim()) {
            flagInvalid(outputDirInput);
            return false;
        }
        return true;
    }

    function flagInvalid(input) {
        input.focus();
        input.style.borderColor = "#e74c3c";
        setTimeout(() => (input.style.borderColor = ""), 1500);
    }

    async function runWorkers(queue, handler) {
        const results = [];
        async function worker() {
            while (queue.length) {
                const item = queue.shift();
                results.push(await handler(item));
            }
        }
        await Promise.all(Array.from(
            { length: Math.min(CONCURRENCY, queue.length) },
            () => worker(),
        ));
        return results;
    }

    async function previewFiles() {
        const queue = files.map((file, index) => ({ file, index }));
        return runWorkers(queue, async ({ file, index }) => {
            updateStatus(index, "processing");
            try {
                const body = new FormData();
                body.append("file", file);
                const response = await fetch("/api/analyze", { method: "POST", body });
                const result = await response.json();
                if (result.status === "success") {
                    previews.set(index, result);
                    updateStatus(index, "preview", result.new_name);
                } else {
                    updateStatus(index, "error", null, result.error);
                }
                return result;
            } catch (error) {
                updateStatus(index, "error", null, error.message);
                return { status: "error", error: error.message };
            }
        });
    }

    async function applyFiles() {
        const queue = Array.from(previews, ([index, preview]) => ({ index, preview }));
        return runWorkers(queue, async ({ index, preview }) => {
            const proposedInput = document.getElementById(`proposal-${index}`);
            const newName = proposedInput ? proposedInput.value.trim() : preview.new_name;
            updateStatus(index, "processing");
            try {
                const response = await fetch("/api/apply", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({
                        filename: preview.original_name,
                        new_name: newName,
                        source_dir: sourceDirInput.value.trim(),
                        mode,
                        output_dir: mode === "copy" ? outputDirInput.value.trim() : null,
                        fingerprint: preview.fingerprint,
                    }),
                });
                const result = await response.json();
                if (result.status === "success") {
                    updateStatus(index, "success", result.new_name);
                } else {
                    updateStatus(index, "error", null, result.error);
                }
                return result;
            } catch (error) {
                updateStatus(index, "error", null, error.message);
                return { status: "error", error: error.message };
            }
        });
    }

    function updateStatus(index, status, newName, error) {
        const item = document.getElementById(`file-${index}`);
        const statusElement = document.getElementById(`status-${index}`);
        if (!item || !statusElement) return;
        item.className = `file-item ${status}`;

        if (status === "processing") {
            statusElement.innerHTML = '<div class="spinner"></div>';
        } else if (status === "preview") {
            statusElement.innerHTML = `<input class="proposed-name" id="proposal-${index}" value="${escapeAttribute(newName)}" aria-label="Proposed filename">`;
        } else if (status === "success") {
            statusElement.innerHTML = `<span class="new-name">${escapeHtml(newName)}</span>`;
        } else if (status === "error") {
            statusElement.innerHTML = `<span class="error-msg">${escapeHtml(error || "Failed")}</span>`;
        }
    }

    function showPreviewSummary(results) {
        const ready = results.filter((result) => result.status === "success").length;
        const errors = results.length - ready;
        resultsSummary.hidden = false;
        resultsSummary.className = errors ? "results-summary has-errors" : "results-summary preview-ready";
        resultsSummary.textContent = errors
            ? `${ready} ready to review; ${errors} could not be read. Edit any filename, then apply the ready changes.`
            : `Review the ${ready} proposed filename${ready === 1 ? "" : "s"}. You can edit them before applying.`;
    }

    function showApplySummary(results) {
        const successes = results.filter((result) => result.status === "success").length;
        const errors = results.length - successes;
        resultsSummary.hidden = false;
        resultsSummary.className = errors ? "results-summary has-errors" : "results-summary all-success";
        resultsSummary.textContent = errors
            ? `${successes} completed; ${errors} failed without changing the source file.`
            : `All ${successes} receipt${successes === 1 ? "" : "s"} ${mode === "copy" ? "copied" : "renamed"} successfully.`;
    }

    function escapeHtml(value) {
        const element = document.createElement("div");
        element.textContent = value;
        return element.innerHTML;
    }

    function escapeAttribute(value) {
        return escapeHtml(value).replace(/"/g, "&quot;");
    }
})();
