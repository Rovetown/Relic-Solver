const test = require("node:test");
const assert = require("node:assert/strict");

const core = require("../../src/webapp/static/js/solver-core.js");

test("the module exports exactly its public helpers", () => {
    assert.deepEqual(Object.keys(core).toSorted(), [
        "fieldProblem",
        "formatPct",
        "isOptionalNumber",
        "resultFrameProblem",
    ]);
});

test.describe("formatPct", () => {
    test("renders ordinary probabilities at two decimals", () => {
        assert.equal(core.formatPct(1), "100.00%");
        assert.equal(core.formatPct(0.5), "50.00%");
        assert.equal(core.formatPct(0.4242), "42.42%");


        assert.equal(core.formatPct(0), "0%");
    });

    test("keeps a tiny probability from reading as impossible", () => {


        assert.equal(core.formatPct(0.0000004), "0.00004%");
        assert.equal(core.formatPct(1e-9), "1e-7%");
    });

    test("the 0.005% boundary behaves either side of itself", () => {

        assert.equal(core.formatPct(0.00005), "0.01%");


        assert.equal(core.formatPct(0.00004999), "0.005%");
        assert.equal(core.formatPct(0.00004), "0.004%");
    });
});

test.describe("resultFrameProblem", () => {
    const valid = {
        probability: 0.42,
        expected_rerolls: 2.3,
        expected_gems: 200,
        solve_time_ms: 12,
    };

    test("accepts a well-formed frame", () => {
        assert.equal(core.resultFrameProblem(valid), null);
    });

    test("accepts null optional fields, which the server really sends", () => {

        assert.equal(core.resultFrameProblem({
            probability: 0,
            expected_rerolls: null,
            expected_gems: null,
            solve_time_ms: null,
        }), null);
    });

    test("accepts a frame carrying only a probability", () => {
        assert.equal(core.resultFrameProblem({probability: 1}), null);
    });

    test("rejects a missing probability, which rendered as NaN%", () => {
        assert.equal(
            core.resultFrameProblem({expected_rerolls: 1}),
            "probability is not a finite number",
        );
    });

    test("rejects a probability that is not a finite number", () => {
        for (const bad of ["0.5", NaN, Infinity, -Infinity, null, true, {}]) {
            assert.equal(
                core.resultFrameProblem({probability: bad}),
                "probability is not a finite number",
                `expected rejection for ${String(bad)}`,
            );
        }
    });

    test("rejects a probability outside 0..1", () => {
        for (const bad of [1.5, -0.1, 100]) {
            assert.equal(
                core.resultFrameProblem({probability: bad}),
                "probability outside 0..1",
                `expected rejection for ${bad}`,
            );
        }
    });

    test("accepts the exact bounds", () => {
        assert.equal(core.resultFrameProblem({probability: 0}), null);
        assert.equal(core.resultFrameProblem({probability: 1}), null);
    });

    test("names whichever optional field is not a number", () => {
        assert.equal(
            core.resultFrameProblem({...valid, expected_rerolls: "2"}),
            "expected_rerolls",
        );
        assert.equal(
            core.resultFrameProblem({...valid, expected_gems: "200"}),
            "expected_gems",
        );
        assert.equal(
            core.resultFrameProblem({...valid, solve_time_ms: NaN}),
            "solve_time_ms",
        );
    });

    test("rejects anything that is not an object", () => {
        for (const bad of [null, undefined, 42, "frame", true]) {
            assert.equal(
                core.resultFrameProblem(bad),
                "not an object",
                `expected rejection for ${String(bad)}`,
            );
        }
    });
});

test.describe("fieldProblem", () => {
    const bounded = {min: "5", max: "36"};

    test("accepts a value inside the bounds", () => {
        assert.equal(core.fieldProblem({value: "20", ...bounded}), null);
    });

    test("accepts the exact bounds", () => {
        assert.equal(core.fieldProblem({value: "5", ...bounded}), null);
        assert.equal(core.fieldProblem({value: "36", ...bounded}), null);
    });

    test("reports an empty field rather than coercing it to zero", () => {


        assert.equal(core.fieldProblem({value: "", ...bounded}), "needs a number");
        assert.equal(core.fieldProblem({value: "   ", ...bounded}), "needs a number");
        assert.equal(core.fieldProblem({value: null, ...bounded}), "needs a number");
    });

    test("reports a non-integer", () => {
        for (const bad of ["abc", "1.5", "1e3x", "--5"]) {
            assert.equal(
                core.fieldProblem({value: bad, ...bounded}),
                "must be a whole number",
                `expected rejection for ${bad}`,
            );
        }
    });

    test("names the bound it missed", () => {
        assert.equal(
            core.fieldProblem({value: "4", ...bounded}),
            "must be 5 or more",
        );
        assert.equal(
            core.fieldProblem({value: "37", ...bounded}),
            "must be 36 or less",
        );
    });

    test("treats an absent bound as unbounded, which is how D1 works", () => {
        assert.equal(core.fieldProblem({value: "999999", min: "0", max: ""}), null);
        assert.equal(core.fieldProblem({value: "-1", min: "", max: ""}), null);
        assert.equal(core.fieldProblem({value: "999999", min: "0"}), null);
    });

    test("still enforces a minimum of zero", () => {
        assert.equal(
            core.fieldProblem({value: "-1", min: "0", max: ""}),
            "must be 0 or more",
        );
    });
});

test.describe("isOptionalNumber", () => {
    test("accepts finite numbers and null-ish values", () => {
        for (const ok of [0, -1, 3.5, null, undefined]) {
            assert.equal(core.isOptionalNumber(ok), true, String(ok));
        }
    });

    test("rejects non-numbers and non-finite numbers", () => {
        for (const bad of ["1", NaN, Infinity, -Infinity, {}, []]) {
            assert.equal(core.isOptionalNumber(bad), false, String(bad));
        }
    });
});
