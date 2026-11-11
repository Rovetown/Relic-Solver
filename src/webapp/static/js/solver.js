(function () {
    "use strict";


    var core = window.RelicSolverCore;

    var btn = document.getElementById("runSolver");
    var progressBar = document.getElementById("progressBar");
    var resultsBox = document.getElementById("results");
    var errorBox = document.getElementById("errorBox");


    var helpToggles = document.querySelectorAll(
        "button[aria-controls][aria-expanded]"
    );
    Array.prototype.forEach.call(helpToggles, function (toggle) {
        toggle.addEventListener("click", function () {
            var panel = document.getElementById(
                toggle.getAttribute("aria-controls")
            );
            if (!panel) {
                return;
            }
            var shown = panel.classList.toggle("show");
            toggle.setAttribute("aria-expanded", shown ? "true" : "false");
        });
    });


    var ETAG_CACHE_MAX = 50;
    var etagCache = new Map();

    function rememberEtag(key, value) {
        if (etagCache.size >= ETAG_CACHE_MAX) {
            etagCache.delete(etagCache.keys().next().value);
        }
        etagCache.set(key, value);
    }


    var REQUEST_TIMEOUT_MS = 120000;


    var STORAGE_KEY = "relicSolverInputs";
    var STORAGE_MAX_AGE_MS = 90 * 24 * 60 * 60 * 1000;
    var inputIds = [
        "totalRelicChests", "totalDivineChests", "relicCap",
        "targetD1", "targetD2", "targetD3", "targetD4", "targetD5",
    ];


    var paramMap = {
        totalRelicChests: "chests",
        totalDivineChests: "divine",
        relicCap: "cap",
        targetD1: "d1",
        targetD2: "d2",
        targetD3: "d3",
        targetD4: "d4",
        targetD5: "d5",
    };

    function loadInputs() {

        var params = new URLSearchParams(window.location.search);
        var hasUrlParams = inputIds.some(function (id) {
            return params.has(paramMap[id]);
        });

        if (hasUrlParams) {
            inputIds.forEach(function (id) {
                var val = params.get(paramMap[id]);
                if (val !== null) {
                    document.getElementById(id).value = val;
                }
            });
        } else {
            try {
                var entry = JSON.parse(localStorage.getItem(STORAGE_KEY));
                if (!entry) return;

                var values = entry.values || entry;
                if (entry.savedAt && Date.now() - entry.savedAt > STORAGE_MAX_AGE_MS) {
                    localStorage.removeItem(STORAGE_KEY);
                    return;
                }
                inputIds.forEach(function (id) {
                    if (values[id] != null) {
                        document.getElementById(id).value = values[id];
                    }
                });
            } catch {}
        }
    }

    function saveInputs() {
        var data = {};
        var params = new URLSearchParams();
        inputIds.forEach(function (id) {
            var val = document.getElementById(id).value;
            data[id] = val;

            if (val !== "" && val !== "0") {
                params.set(paramMap[id], val);
            }
        });


        var qs = params.toString();
        var newUrl = window.location.pathname + (qs ? "?" + qs : "");
        history.replaceState(null, "", newUrl);

        try {
            localStorage.setItem(
                STORAGE_KEY,
                JSON.stringify({savedAt: Date.now(), values: data}),
            );
        } catch {}
    }

    loadInputs();


    inputIds.forEach(function (id) {
        var el = document.getElementById(id);
        var val = parseInt(el.value, 10);
        if (isNaN(val)) {
            el.value = el.defaultValue;
        } else {
            if (el.min !== "" && val < parseInt(el.min, 10)) el.value = el.min;
            if (el.max !== "" && val > parseInt(el.max, 10)) el.value = el.max;
        }
    });


    var saveTimer = null;

    function saveInputsSoon() {
        if (saveTimer !== null) clearTimeout(saveTimer);
        saveTimer = setTimeout(function () {
            saveTimer = null;
            saveInputs();
        }, 400);
    }

    function flushSaveInputs() {
        if (saveTimer !== null) {
            clearTimeout(saveTimer);
            saveTimer = null;
        }
        saveInputs();
    }

    inputIds.forEach(function (id) {
        var el = document.getElementById(id);
        el.addEventListener("input", saveInputsSoon);

        el.addEventListener("input", function () {
            el.setAttribute("aria-invalid", "false");
        });
    });


    function labelTextFor(el) {
        var label = document.querySelector('label[for="' + el.id + '"]');
        return label ? label.textContent.trim() : el.id;
    }


    function validateInputs() {
        var problems = [];
        inputIds.forEach(function (id) {
            var el = document.getElementById(id);
            var problem = core.fieldProblem({
                value: el.value,
                min: el.min,
                max: el.max,
            });
            el.setAttribute("aria-invalid", problem ? "true" : "false");
            if (problem) {
                problems.push({el: el, text: labelTextFor(el) + " " + problem + "."});
            }
        });
        if (problems.length === 0) return true;
        showError(problems.map(function (p) { return p.text; }).join(" "));
        problems[0].el.focus();
        return false;
    }

    function getInt(id) {
        var el = document.getElementById(id);
        var val = parseInt(el.value, 10);
        return isNaN(val) ? 0 : val;
    }

    var barInner = progressBar.querySelector(".progress-bar");

    function resetProgressBar() {
        barInner.classList.add("progress-bar-striped", "progress-bar-animated");
        barInner.style.width = "100%";
    }

    function showResult(data) {
        progressBar.classList.remove("visible");
        btn.disabled = false;

        var prob = data.probability;
        var pct = core.formatPct(prob);
        var probEl = document.getElementById("resultProbability");
        var rerollsEl = document.getElementById("resultRerolls");
        var gemsEl = document.getElementById("resultGems");
        var gemsRow = document.getElementById("resultGemsRow");
        var timeEl = document.getElementById("resultTime");

        if (prob === 0) {
            probEl.textContent = "Impossible - 0% chance";
            probEl.className = "result-probability result-impossible";
            rerollsEl.textContent = "";
            gemsEl.textContent = "";
            gemsRow.classList.remove("visible");
        } else {
            probEl.textContent = pct;
            probEl.className = "result-probability";
            if (data.expected_rerolls != null) {


                var rerolls = Math.ceil(Math.round(data.expected_rerolls * 1e9) / 1e9);
                rerollsEl.textContent = "~" + rerolls.toLocaleString() + " rerolls";
            } else {
                rerollsEl.textContent = "";
            }
            if (data.expected_gems != null) {
                gemsEl.textContent =
                    "~" + Math.round(data.expected_gems).toLocaleString() +
                    " gems";
                gemsRow.classList.add("visible");
            } else {
                gemsEl.textContent = "";
                gemsRow.classList.remove("visible");
            }
        }
        if (data.solve_time_ms != null) {
            timeEl.textContent = data.solve_time_ms < 1000
                ? data.solve_time_ms + "ms"
                : (data.solve_time_ms / 1000).toFixed(1) + "s";
        } else {
            timeEl.textContent = "";
        }
        resultsBox.classList.add("visible");
    }

    function renderResult(data) {
        var problem = core.resultFrameProblem(data);
        if (problem) {
            throw new Error(
                "The server sent a result this page could not read (" +
                problem + "). Please try again."
            );
        }
        showResult(data);
    }

    function showError(message) {
        progressBar.classList.remove("visible");
        resetProgressBar();
        btn.disabled = false;
        document.getElementById("errorMessage").textContent = message;
        errorBox.classList.add("visible");
    }


    function isOurScript(filename) {
        return typeof filename === "string" &&
            filename.indexOf(window.location.origin + "/static/") === 0;
    }

    window.addEventListener("error", function (event) {
        if (!isOurScript(event.filename)) return;
        if (errorBox.classList.contains("visible")) return;
        showError(
            "Something went wrong in the page: " +
            (event.message || "unknown error") + ". Please reload."
        );
    });

    window.addEventListener("unhandledrejection", function (event) {


        if (window.console && console.warn) {
            console.warn("Unhandled rejection:", event.reason);
        }
    });

    document.getElementById("solverForm").addEventListener("submit", function (e) {
        e.preventDefault();

        resultsBox.classList.remove("visible");
        errorBox.classList.remove("visible");
        if (!validateInputs()) return;

        var payload = {
            total_relic_chests: getInt("totalRelicChests"),
            divine_chests: getInt("totalDivineChests"),
            relic_cap: getInt("relicCap"),
            targets: [
                getInt("targetD1"),
                getInt("targetD2"),
                getInt("targetD3"),
                getInt("targetD4"),
                getInt("targetD5"),
            ],
        };

        resetProgressBar();
        progressBar.classList.add("visible");
        btn.disabled = true;


        flushSaveInputs();

        var bodyStr = JSON.stringify(payload);
        var fetchHeaders = {"Content-Type": "application/json"};
        var cached = etagCache.get(bodyStr);
        if (cached) {
            fetchHeaders["If-None-Match"] = cached.etag;
        }

        var controller = new AbortController();
        var timedOut = false;
        var timeoutId = setTimeout(function () {
            timedOut = true;
            controller.abort();
        }, REQUEST_TIMEOUT_MS);


        var activeReader = null;

        fetch("/solve", {
            method: "POST",
            headers: fetchHeaders,
            body: bodyStr,
            signal: controller.signal,
        })
            .then(function (resp) {

                if (resp.status === 304 && cached) {
                    renderResult(cached.data);
                    return;
                }

                var etag = resp.headers.get("ETag");
                var ct = resp.headers.get("content-type") || "";


                if (ct.includes("application/json")) {
                    return resp.json().then(function (data) {
                        if (data.error) throw new Error(data.error);
                        renderResult(data);
                    });
                }


                if (!ct.includes("ndjson")) {
                    throw new Error(
                        "Server returned unexpected content type (HTTP " + resp.status + "). " +
                        "The calculation likely timed out -- try reducing the cap or target values."
                    );
                }

                var reader = resp.body.getReader();
                activeReader = reader;
                var decoder = new TextDecoder();
                var buffer = "";
                var firstProgress = true;


                var sawTerminalFrame = false;

                function processLines() {
                    var lines = buffer.split("\n");

                    buffer = lines.pop();
                    lines.forEach(function (line) {
                        line = line.trim();
                        if (!line) return;
                        var msg;
                        try {
                            msg = JSON.parse(line);
                        } catch {
                            return;
                        }

                        if (msg.type === "progress" && msg.percent >= 0) {
                            if (firstProgress) {
                                barInner.classList.remove("progress-bar-striped", "progress-bar-animated");
                                barInner.style.width = "0%";
                                firstProgress = false;
                            }
                            barInner.style.width = msg.percent + "%";
                        } else if (msg.type === "result") {
                            sawTerminalFrame = true;
                            resetProgressBar();
                            renderResult(msg);


                            if (etag) {
                                rememberEtag(bodyStr, {etag: etag, data: msg});
                            }
                        } else if (msg.type === "error") {
                            sawTerminalFrame = true;
                            throw new Error(msg.error);
                        }
                    });
                }

                function pump() {
                    return reader.read().then(function (result) {
                        if (result.done) {

                            if (buffer.trim()) processLines();
                            if (!sawTerminalFrame) {
                                resetProgressBar();
                                throw new Error(
                                    "The connection closed before a result arrived. " +
                                    "The server may have restarted -- please try again."
                                );
                            }
                            return;
                        }
                        buffer += decoder.decode(result.value, {stream: true});
                        processLines();
                        return pump();
                    });
                }

                return pump();
            })
            .catch(function (err) {
                if (activeReader) {

                    activeReader.cancel().catch(function () {});
                }
                if (timedOut || err.name === "AbortError") {
                    resetProgressBar();
                    showError(
                        "The request took too long and was stopped. The server " +
                        "may be busy -- please try again."
                    );
                    return;
                }
                showError(err.message);
            })
            .then(function () {
                clearTimeout(timeoutId);
                activeReader = null;
            });
    });
})();


(function () {
    "use strict";

    var KEY = "relicSolver.whatsNew";
    var VERSION = "2026-10-24";

    var dialog = document.getElementById("whatsNew");


    if (!dialog || typeof dialog.showModal !== "function") {
        return;
    }


    try {
        if (localStorage.getItem(KEY) === VERSION) {
            return;
        }
    } catch {

    }

    dialog.showModal();

    var dismiss = dialog.querySelector("[data-whatsnew-dismiss]");
    if (dismiss) {
        dismiss.addEventListener("click", function () {
            try {
                localStorage.setItem(KEY, VERSION);
            } catch {

            }
            dialog.close();
        });
    }
})();
