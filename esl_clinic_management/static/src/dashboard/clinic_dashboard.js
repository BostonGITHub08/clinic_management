import { Component, onMounted, onWillStart, onWillUnmount, useRef, useState } from "@odoo/owl";
import { loadBundle } from "@web/core/assets";
import { _t } from "@web/core/l10n/translation";
import { registry } from "@web/core/registry";
import { user } from "@web/core/user";
import { useService } from "@web/core/utils/hooks";
import { formatMonetary } from "@web/views/fields/formatters";

const COLORS = {
    teal: "#0e9f9a",
    blue: "#3b82f6",
    green: "#22c55e",
    red: "#ef4444",
    amber: "#f59e0b",
    violet: "#8b5cf6",
};

// KPI values that are animated with a count-up effect
const ANIMATED_KPIS = [
    "total_patients", "new_patients", "appointments", "admitted", "available_beds",
    "occupied_beds", "discharges", "doctors", "revenue", "pending", "occupancy_rate",
];

const AVATAR_COLORS = ["#0e9f9a", "#3b82f6", "#8b5cf6", "#ec4899", "#f59e0b", "#22c55e", "#ef4444", "#06b6d4"];

function hexToRgba(hex, alpha) {
    const value = parseInt(hex.slice(1), 16);
    return `rgba(${(value >> 16) & 255}, ${(value >> 8) & 255}, ${value & 255}, ${alpha})`;
}

/** Vertical gradient fill for bar/line datasets, computed once the chart area is known. */
function verticalGradient(hex, from = 0.05, to = 0.45) {
    return (context) => {
        const { ctx, chartArea } = context.chart;
        if (!chartArea) {
            return hexToRgba(hex, to);
        }
        const gradient = ctx.createLinearGradient(0, chartArea.bottom, 0, chartArea.top);
        gradient.addColorStop(0, hexToRgba(hex, from));
        gradient.addColorStop(1, hexToRgba(hex, to));
        return gradient;
    };
}

export class ClinicDashboard extends Component {
    static template = "esl_clinic_management.Dashboard";
    static props = ["*"];

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.state = useState({
            period: "today",
            dateFrom: "",
            dateTo: "",
            data: null,
            loading: true,
            updatedAt: "",
        });
        this.anim = useState(Object.fromEntries(ANIMATED_KPIS.map((k) => [k, 0])));
        this.reducedMotion = window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
        this.charts = {};
        this.chartRefs = {
            revenue: useRef("revenueChart"),
            appointments: useRef("appointmentChart"),
            admissions: useRef("admissionChart"),
            beds: useRef("bedChart"),
        };
        this.periods = [
            { key: "today", label: _t("Today") },
            { key: "week", label: _t("This Week") },
            { key: "month", label: _t("This Month") },
            { key: "custom", label: _t("Custom") },
        ];
        this.quickActions = [
            { label: _t("New Patient"), icon: "fa-user-plus", model: "clinic.patient" },
            { label: _t("Book Appointment"), icon: "fa-calendar-plus-o", model: "clinic.appointment" },
            { label: _t("Admit Patient"), icon: "fa-bed", model: "clinic.admission" },
            { label: _t("Lab Request"), icon: "fa-flask", model: "clinic.lab.request" },
        ];

        onWillStart(async () => {
            await loadBundle("web.chartjs_lib");
            await this.loadData();
        });
        onMounted(() => {
            this.renderCharts();
            this.animateKpis();
        });
        onWillUnmount(() => {
            cancelAnimationFrame(this.rafId);
            this.destroyCharts();
        });
    }

    // ------------------------------------------------------------------ data
    async loadData() {
        this.state.loading = true;
        const { period, dateFrom, dateTo } = this.state;
        this.state.data = await this.orm.call("clinic.dashboard", "get_dashboard_data", [
            period,
            dateFrom || false,
            dateTo || false,
        ]);
        this.state.updatedAt = new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
        this.state.loading = false;
    }

    async setPeriod(period) {
        this.state.period = period;
        if (period === "custom" && !(this.state.dateFrom && this.state.dateTo)) {
            return; // wait until both dates are picked
        }
        await this.refresh();
    }

    async onDateChange(field, ev) {
        this.state[field] = ev.target.value;
        if (this.state.dateFrom && this.state.dateTo) {
            await this.refresh();
        }
    }

    async refresh() {
        await this.loadData();
        this.renderCharts();
        this.animateKpis();
    }

    /** Count every KPI from its current value up (or down) to the new one. */
    animateKpis() {
        const target = this.state.data.kpis;
        cancelAnimationFrame(this.rafId);
        if (this.reducedMotion) {
            Object.assign(this.anim, target);
            return;
        }
        const from = { ...this.anim };
        const start = performance.now();
        const duration = 1100;
        const step = (now) => {
            const t = Math.min(1, (now - start) / duration);
            const eased = 1 - Math.pow(1 - t, 4);
            for (const key of ANIMATED_KPIS) {
                this.anim[key] = from[key] + (target[key] - from[key]) * eased;
            }
            if (t < 1) {
                this.rafId = requestAnimationFrame(step);
            }
        };
        this.rafId = requestAnimationFrame(step);
    }

    // ------------------------------------------------------------------ helpers
    get kpis() {
        return this.state.data.kpis;
    }

    get greeting() {
        const hour = new Date().getHours();
        const part = hour < 12 ? _t("Good morning") : hour < 18 ? _t("Good afternoon") : _t("Good evening");
        return `${part}, ${user.name}`;
    }

    get todayLabel() {
        return new Date().toLocaleDateString([], { weekday: "long", day: "numeric", month: "long", year: "numeric" });
    }

    get periodLabel() {
        if (this.state.period === "custom") {
            const { start, end } = this.state.data.period;
            return `${start} → ${end}`;
        }
        return this.periods.find((p) => p.key === this.state.period).label;
    }

    get kpiCards() {
        const a = this.anim;
        const k = this.kpis;
        const n = (v) => Math.round(v).toLocaleString();
        return [
            { key: "patients", icon: "fa-users", color: "teal", value: n(a.total_patients), label: _t("Total Patients"),
              sub: `+${k.new_patients} ${_t("new")}` },
            { key: "appointments", icon: "fa-calendar-check-o", color: "blue", value: n(a.appointments), label: _t("Appointments"),
              sub: this.periodLabel },
            { key: "admitted", icon: "fa-h-square", color: "violet", value: n(a.admitted), label: _t("Currently Admitted"),
              sub: _t("in-patients now") },
            { key: "available_beds", icon: "fa-check-circle", color: "green", value: n(a.available_beds), label: _t("Available Beds"),
              sub: `${k.maintenance_beds} ${_t("in maintenance")}` },
            { key: "occupied_beds", icon: "fa-bed", color: "red", value: n(a.occupied_beds), label: _t("Occupied Beds"),
              sub: `${Math.round(a.occupancy_rate)}% ${_t("occupancy")}`, progress: k.occupancy_rate },
            { key: "discharges", icon: "fa-sign-out", color: "amber", value: n(a.discharges), label: _t("Discharges"),
              sub: this.periodLabel },
            { key: "doctors", icon: "fa-user-md", color: "blue", value: n(a.doctors), label: _t("Doctors"),
              sub: _t("active") },
            { key: "revenue", icon: "fa-line-chart", color: "green", value: this.money(a.revenue), label: _t("Revenue"),
              sub: this.periodLabel },
            { key: "pending", icon: "fa-hourglass-half", color: "amber", value: this.money(a.pending), label: _t("Pending Payments"),
              sub: `${k.pending_count} ${_t("unpaid invoices")}` },
            { key: "new_patients", icon: "fa-user-plus", color: "teal", value: n(a.new_patients), label: _t("New Registrations"),
              sub: this.periodLabel },
        ];
    }

    money(value) {
        return formatMonetary(value, { currencyId: this.state.data.currency_id });
    }

    initials(name) {
        return (name || "?").split(/\s+/).filter(Boolean).slice(0, 2).map((w) => w[0].toUpperCase()).join("");
    }

    avatarStyle(id) {
        return `background-color: ${AVATAR_COLORS[id % AVATAR_COLORS.length]}`;
    }

    stateClass(state) {
        return {
            draft: "o_clinic_pill_grey",
            confirmed: "o_clinic_pill_blue",
            checked_in: "o_clinic_pill_teal",
            in_consultation: "o_clinic_pill_amber",
            done: "o_clinic_pill_green",
            cancelled: "o_clinic_pill_red",
            no_show: "o_clinic_pill_red",
        }[state] || "o_clinic_pill_grey";
    }

    occupancyClass(rate) {
        return rate >= 85 ? "o_clinic_bar_red" : rate >= 60 ? "o_clinic_bar_amber" : "o_clinic_bar_green";
    }

    // ------------------------------------------------------------------ navigation
    openAction(name, resModel, domain = [], views = ["list", "form"], context = {}) {
        this.action.doAction({
            type: "ir.actions.act_window",
            name,
            res_model: resModel,
            domain,
            context,
            views: views.map((v) => [false, v]),
        });
    }

    openRecord(resModel, resId) {
        this.action.doAction({
            type: "ir.actions.act_window",
            res_model: resModel,
            res_id: resId,
            views: [[false, "form"]],
        });
    }

    openNew(quickAction) {
        this.action.doAction({
            type: "ir.actions.act_window",
            name: quickAction.label,
            res_model: quickAction.model,
            views: [[false, "form"]],
            target: "current",
        });
    }

    openKpi(key) {
        const d = this.state.data.domains;
        const actions = {
            patients: () => this.openAction(_t("Patients"), "clinic.patient", [], ["kanban", "list", "form"]),
            new_patients: () => this.openAction(_t("New Patients"), "clinic.patient", d.new_patients),
            appointments: () => this.openAction(_t("Appointments"), "clinic.appointment", d.appointments, ["list", "calendar", "form"]),
            admitted: () => this.openAction(_t("Admitted Patients"), "clinic.admission", [["state", "=", "admitted"]]),
            available_beds: () => this.openAction(_t("Available Beds"), "clinic.bed", [["state", "=", "available"]], ["kanban", "list", "form"]),
            occupied_beds: () => this.openAction(_t("Occupied Beds"), "clinic.bed", [["state", "=", "occupied"]], ["kanban", "list", "form"]),
            discharges: () => this.openAction(_t("Discharges"), "clinic.discharge", d.discharges),
            doctors: () => this.openAction(_t("Doctors"), "clinic.doctor", [], ["kanban", "list", "form"]),
            revenue: () => this.openAction(_t("Revenue"), "account.move", d.revenue, ["list", "form"], { create: false }),
            pending: () => this.openAction(_t("Pending Payments"), "account.move", d.pending, ["list", "form"], { create: false }),
        };
        actions[key]();
    }

    // ------------------------------------------------------------------ charts
    destroyCharts() {
        for (const chart of Object.values(this.charts)) {
            chart.destroy();
        }
        this.charts = {};
    }

    renderCharts() {
        if (!this.state.data) {
            return;
        }
        this.destroyCharts();
        const charts = this.state.data.charts;
        const style = getComputedStyle(document.body);
        const textColor = style.getPropertyValue("--bs-secondary-color").trim() || "#6b7280";
        const gridColor = style.getPropertyValue("--bs-border-color-translucent").trim() || "rgba(0,0,0,0.08)";
        const animation = this.reducedMotion ? false : { duration: 1200, easing: "easeOutQuart" };
        const scales = {
            x: { grid: { display: false }, ticks: { color: textColor }, border: { display: false } },
            y: { beginAtZero: true, grid: { color: gridColor }, ticks: { color: textColor, precision: 0 }, border: { display: false } },
        };
        const baseOptions = {
            responsive: true,
            maintainAspectRatio: false,
            animation,
            interaction: { mode: "index", intersect: false },
            plugins: {
                legend: { position: "bottom", labels: { color: textColor, usePointStyle: true, pointStyle: "circle", boxWidth: 8, padding: 16 } },
                tooltip: { backgroundColor: "rgba(17, 24, 39, 0.92)", padding: 10, cornerRadius: 8, boxPadding: 4 },
            },
        };
        const make = (key, config) => {
            const el = this.chartRefs[key].el;
            if (el) {
                this.charts[key] = new Chart(el, config);
            }
        };

        make("revenue", {
            type: "bar",
            data: {
                labels: charts.revenue.labels,
                datasets: [{
                    label: _t("Revenue"),
                    data: charts.revenue.values,
                    backgroundColor: verticalGradient(COLORS.teal, 0.35, 0.95),
                    hoverBackgroundColor: COLORS.teal,
                    borderRadius: 8,
                    borderSkipped: false,
                    maxBarThickness: 34,
                }],
            },
            options: {
                ...baseOptions,
                animation: animation && { ...animation, delay: (ctx) => ctx.dataIndex * 60 },
                plugins: {
                    ...baseOptions.plugins,
                    legend: { display: false },
                    tooltip: { ...baseOptions.plugins.tooltip, callbacks: { label: (ctx) => this.money(ctx.parsed.y) } },
                },
                scales: { ...scales, y: { ...scales.y, ticks: { ...scales.y.ticks, precision: undefined } } },
            },
        });

        make("appointments", {
            type: "bar",
            data: {
                labels: charts.appointments.labels,
                datasets: [
                    { label: _t("Scheduled"), data: charts.appointments.scheduled, backgroundColor: verticalGradient(COLORS.blue, 0.25, 0.85),
                      borderRadius: 8, borderSkipped: false, maxBarThickness: 26 },
                    { label: _t("Completed"), data: charts.appointments.completed, backgroundColor: verticalGradient(COLORS.green, 0.35, 0.95),
                      borderRadius: 8, borderSkipped: false, maxBarThickness: 26 },
                ],
            },
            options: { ...baseOptions, animation: animation && { ...animation, delay: (ctx) => ctx.dataIndex * 70 }, scales },
        });

        make("admissions", {
            type: "line",
            data: {
                labels: charts.admissions.labels,
                datasets: [
                    { label: _t("Admissions"), data: charts.admissions.admissions, borderColor: COLORS.violet,
                      backgroundColor: verticalGradient(COLORS.violet, 0.0, 0.3), fill: true, tension: 0.4, borderWidth: 3,
                      pointRadius: 4, pointHoverRadius: 7, pointBackgroundColor: "#fff", pointBorderWidth: 2 },
                    { label: _t("Discharges"), data: charts.admissions.discharges, borderColor: COLORS.teal,
                      backgroundColor: verticalGradient(COLORS.teal, 0.0, 0.25), fill: true, tension: 0.4, borderWidth: 3,
                      pointRadius: 4, pointHoverRadius: 7, pointBackgroundColor: "#fff", pointBorderWidth: 2 },
                ],
            },
            options: { ...baseOptions, scales },
        });

        const occupancy = this.kpis.occupancy_rate;
        make("beds", {
            type: "doughnut",
            data: {
                labels: charts.beds.labels,
                datasets: [{
                    data: charts.beds.values,
                    backgroundColor: [COLORS.green, COLORS.red, COLORS.amber],
                    hoverOffset: 8,
                    borderWidth: 0,
                    spacing: 3,
                    borderRadius: 6,
                }],
            },
            options: {
                ...baseOptions,
                cutout: "74%",
                animation: animation && { ...animation, animateRotate: true, animateScale: true },
                plugins: { ...baseOptions.plugins, legend: { display: false } },
            },
            plugins: [{
                id: "clinicCenterText",
                afterDraw(chart) {
                    const { ctx, chartArea } = chart;
                    const x = (chartArea.left + chartArea.right) / 2;
                    const y = (chartArea.top + chartArea.bottom) / 2;
                    ctx.save();
                    ctx.textAlign = "center";
                    ctx.textBaseline = "middle";
                    ctx.fillStyle = style.getPropertyValue("--bs-body-color").trim() || "#111827";
                    ctx.font = "700 24px system-ui, sans-serif";
                    ctx.fillText(`${Math.round(occupancy)}%`, x, y - 8);
                    ctx.fillStyle = textColor;
                    ctx.font = "500 11px system-ui, sans-serif";
                    ctx.fillText(_t("occupied"), x, y + 14);
                    ctx.restore();
                },
            }],
        });
    }
}

registry.category("actions").add("esl_clinic_management.dashboard", ClinicDashboard);
