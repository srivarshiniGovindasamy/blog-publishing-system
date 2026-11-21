/**
 * main.js — Foundation JavaScript
 * =================================
 * Handles:
 *   • Mobile navigation toggle
 *   • Flash-message dismissal
 *   • Scroll-triggered card animations
 *   • Sticky header background on scroll
 */

document.addEventListener("DOMContentLoaded", () => {

    // ── Mobile Navigation Toggle ──────────────────────────────
    const navToggle = document.getElementById("nav-toggle");
    const navLinks  = document.getElementById("nav-links");

    if (navToggle && navLinks) {
        navToggle.addEventListener("click", () => {
            navToggle.classList.toggle("open");
            navLinks.classList.toggle("open");
        });

        // Close menu when a link is clicked
        navLinks.querySelectorAll(".nav-link").forEach(link => {
            link.addEventListener("click", () => {
                navToggle.classList.remove("open");
                navLinks.classList.remove("open");
            });
        });
    }

    document.querySelectorAll("form[data-confirm]").forEach(form => {
        form.addEventListener("submit", event => {
            if (!window.confirm(form.dataset.confirm)) {
                event.preventDefault();
            }
        });
    });

    // ── Flash Message Dismissal ───────────────────────────────
    document.querySelectorAll(".flash-close").forEach(btn => {
        btn.addEventListener("click", () => {
            const flash = btn.closest(".flash");
            flash.style.opacity = "0";
            flash.style.transform = "translateY(-12px)";
            setTimeout(() => flash.remove(), 250);
        });
    });

    // ── Scroll-Triggered Animations ───────────────────────────
    const observerOptions = {
        threshold: 0.15,
        rootMargin: "0px 0px -40px 0px"
    };

    const observer = new IntersectionObserver((entries) => {
        entries.forEach(entry => {
            if (entry.isIntersecting) {
                entry.target.classList.add("animate-in");
                observer.unobserve(entry.target);
            }
        });
    }, observerOptions);

    // Observe all cards and status cards
    document.querySelectorAll(".card, .status-card").forEach(el => {
        el.style.opacity = "0";
        observer.observe(el);
    });

    // ── Header Background on Scroll ──────────────────────────
    const header = document.getElementById("site-header");
    if (header) {
        window.addEventListener("scroll", () => {
            if (window.scrollY > 50) {
                header.style.background = "rgba(15, 15, 20, 0.92)";
            } else {
                header.style.background = "rgba(15, 15, 20, 0.75)";
            }
        }, { passive: true });
    }

    // ── Smooth Scroll for Anchor Links ────────────────────────
    document.querySelectorAll('a[href^="#"]').forEach(anchor => {
        anchor.addEventListener("click", (e) => {
            const targetId = anchor.getAttribute("href");
            if (targetId === "#") return;
            const target = document.querySelector(targetId);
            if (target) {
                e.preventDefault();
                target.scrollIntoView({ behavior: "smooth", block: "start" });
            }
        });
    });
});
