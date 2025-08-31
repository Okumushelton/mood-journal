// main.js
document.addEventListener("DOMContentLoaded", () => {
    // --- Signup Form ---
    const signupForm = document.getElementById("signupForm");
    if (signupForm) {
        signupForm.addEventListener("submit", async (e) => {
            e.preventDefault();

            const data = {
                username: document.getElementById("username").value,
                email: document.getElementById("email").value,
                password: document.getElementById("password").value,
            };

            try {
                const res = await fetch("/api/signup", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify(data),
                });

                const result = await res.json();
                if (res.ok) {
                    alert("Account created successfully! Please log in.");
                    window.location.href = "/login"; // redirect
                } else {
                    alert("Error: " + (result.error || "Unknown error"));
                }
            } catch (err) {
                console.error("Signup failed", err);
                alert("Something went wrong. Please try again.");
            }
        });
    }

    // --- Login Form (AJAX) ---
    const loginForm = document.getElementById("loginForm");
    if (loginForm) {
        loginForm.addEventListener("submit", async (e) => {
            e.preventDefault();

            const data = {
                username: document.querySelector('input[name="username"]').value,
                password: document.querySelector('input[name="password"]').value
            };

            try {
                const res = await fetch("/api/login", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify(data),
                });

                const result = await res.json();
                if (res.ok) {
                    window.location.href = "/dashboard"; // redirect to dashboard
                } else {
                    alert(result.error || "Login failed");
                }
            } catch (err) {
                console.error("Login failed", err);
                alert("Something went wrong. Please try again.");
            }
        });
    }

    // --- Journal Entry Form ---
    const entryForm = document.getElementById("entry-form");
    if (entryForm) {
        entryForm.addEventListener("submit", async (e) => {
            e.preventDefault();

            const content = document.querySelector('textarea[name="content"]').value;

            try {
                const res = await fetch("/dashboard", {
                    method: "POST",
                    headers: { "Content-Type": "application/x-www-form-urlencoded" },
                    body: new URLSearchParams({ content })
                });

                if (res.ok) {
                    alert("Entry saved successfully!");
                    window.location.reload();
                } else {
                    const result = await res.json();
                    alert(result.error || "Failed to save entry");
                }
            } catch (err) {
                console.error("Entry submission failed", err);
                alert("Something went wrong. Please try again.");
            }
        });
    }

    // --- Dashboard Chart ---
    const dashboardCanvas = document.getElementById("moodChart");
    if (dashboardCanvas) {
        fetch("/entries") // you will need a route to return JSON entries
            .then(res => res.json())
            .then(data => {
                const labels = data.map(entry => entry.date);
                const moods = data.map(entry => entry.mood);

                new Chart(dashboardCanvas, {
                    type: "line",
                    data: {
                        labels: labels,
                        datasets: [{
                            label: "Mood Over Time",
                            data: moods,
                            borderColor: "#4a90e2",
                            backgroundColor: "rgba(74,144,226,0.2)",
                            fill: true,
                            tension: 0.3
                        }]
                    },
                    options: {
                        responsive: true,
                        scales: {
                            y: {
                                beginAtZero: true,
                                ticks: { stepSize: 1 }
                            }
                        }
                    }
                });
            });
    }
});
