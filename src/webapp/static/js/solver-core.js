(function () {
    "use strict";


    function formatPct(prob) {
        var pct = prob * 100;
        if (pct >= 0.005) {
            return pct.toFixed(2) + "%";
        }
        return parseFloat(pct.toPrecision(3)) + "%";
    }

    function isOptionalNumber(value) {
        return value == null || (typeof value === "number" && isFinite(value));
    }


    function resultFrameProblem(data) {
        if (data === null || typeof data !== "object") return "not an object";
        if (typeof data.probability !== "number" || !isFinite(data.probability)) {
            return "probability is not a finite number";
        }
        if (data.probability < 0 || data.probability > 1) {
            return "probability outside 0..1";
        }
        if (!isOptionalNumber(data.expected_rerolls)) return "expected_rerolls";
        if (!isOptionalNumber(data.expected_gems)) return "expected_gems";
        if (!isOptionalNumber(data.solve_time_ms)) return "solve_time_ms";
        return null;
    }


    function fieldProblem(field) {
        var raw = String(field.value == null ? "" : field.value).trim();
        if (raw === "") return "needs a number";
        var val = Number(raw);
        if (!Number.isInteger(val)) return "must be a whole number";
        if (field.min !== "" && field.min != null && val < Number(field.min)) {
            return "must be " + field.min + " or more";
        }
        if (field.max !== "" && field.max != null && val > Number(field.max)) {
            return "must be " + field.max + " or less";
        }
        return null;
    }

    var api = {
        formatPct: formatPct,
        isOptionalNumber: isOptionalNumber,
        resultFrameProblem: resultFrameProblem,
        fieldProblem: fieldProblem,
    };

    if (typeof module === "object" && module.exports) {
        module.exports = api;
    } else {
        globalThis.RelicSolverCore = api;
    }
})();
