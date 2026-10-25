(function () {
  const canvas = document.getElementById("area-case-trend-chart") || document.getElementById("overview-case-volume-chart") || document.getElementById("district-case-chart");
  const pieCanvas = document.getElementById("district-case-pie-chart") || document.getElementById("overview-district-pie-chart");
  const source = document.getElementById("area-activity-chart-data");
  if (!source || typeof Chart === "undefined") return;

  const chartData = JSON.parse(source.textContent);
  const districts = chartData;
  if (!districts.length) return;

  if (canvas) {
    const labels = districts[0].trend.map((point) => point.label);
    const pointRadius = labels.length > 12 ? 0 : 2.5;
    const hoverRadius = labels.length > 12 ? 4 : 5;

    new Chart(canvas, {
    type: "line",
    data: {
      labels,
      datasets: districts.map((district) => ({
        label: district.label,
        data: district.trend.map((point) => point.value),
          borderColor: district.color,
          backgroundColor: district.color,
          borderWidth: 2.5,
          borderCapStyle: "round",
          borderJoinStyle: "round",
          pointRadius,
          pointHoverRadius: hoverRadius,
          pointHoverBorderWidth: 3,
          pointBackgroundColor: "#ffffff",
          pointBorderColor: district.color,
          pointHoverBackgroundColor: district.color,
          pointHoverBorderColor: "#ffffff",
          tension: 0.34,
          fill: false,
          spanGaps: true,
      })),
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      animation: {duration: 450, easing: "easeOutQuart"},
      interaction: {mode: "index", intersect: false},
      layout: {padding: {top: 8, right: 12, bottom: 2, left: 4}},
      plugins: {
        legend: {display: false},
        tooltip: {
          displayColors: true,
          backgroundColor: "#102a43",
          borderColor: "rgba(126, 207, 235, .45)",
          borderWidth: 1,
          cornerRadius: 10,
          padding: 11,
          titleColor: "#ffffff",
          bodyColor: "#d9f3ff",
          titleFont: {size: 11, weight: "800"},
          bodyFont: {size: 11, weight: "600"},
          bodySpacing: 5,
          callbacks: {
            label: (context) => `${context.dataset.label}: ${context.parsed.y} case${context.parsed.y === 1 ? "" : "s"}`,
          },
        },
      },
      scales: {
        x: {
          grid: {color: "rgba(83, 111, 132, .10)", drawBorder: false},
          ticks: {
            color: "#708292",
            maxTicksLimit: labels.length > 12 ? 10 : 12,
            maxRotation: 0,
            autoSkip: true,
            font: {size: 10},
          },
        },
        y: {
          beginAtZero: true,
          suggestedMax: 1,
          title: {display: true, text: "Cases", color: "#506575", font: {size: 10, weight: "700"}},
          grid: {color: "rgba(83, 111, 132, .12)", drawBorder: false},
          border: {display: false},
          ticks: {color: "#708292", precision: 0, stepSize: 1, padding: 8, font: {size: 10}},
        },
      },
    },
    });
  }

  if (!pieCanvas) return;

  const pieTotal = document.querySelector("[data-district-pie-total]");
  const pieLegend = document.querySelector("[data-district-pie-legend]");
  const pieUpdated = document.querySelector("[data-district-pie-updated]");
  const pieCard = document.querySelector("[data-district-pie-card], [data-overview-pie-card]");
  const liveUrl = pieCard && pieCard.dataset.liveUrl;
  const pieColors = ["#1769aa", "#00a896", "#f28f3b", "#e45756", "#7251b5", "#3a9d8f", "#efb366", "#4d77a8"];
  let pieChart;

  function drawPie(data, total, updatedAt) {
    const labels = data.map((district) => district.label);
    const values = data.map((district) => district.count || 0);
    const colors = data.map((district, index) => district.color || pieColors[index % pieColors.length]);
    const chartData = {
      labels,
      datasets: [{
        data: values,
        backgroundColor: colors,
        borderColor: "#ffffff",
        borderWidth: 3,
        hoverOffset: 14,
        hoverBorderWidth: 4,
      }],
    };

    if (pieChart) {
      pieChart.data = chartData;
      pieChart.update();
    } else {
      pieChart = new Chart(pieCanvas, {
        type: "doughnut",
        data: chartData,
        options: {
          responsive: true,
          maintainAspectRatio: false,
          cutout: "62%",
          animation: {duration: 650, easing: "easeOutQuart"},
          plugins: {
            legend: {display: false},
            tooltip: {
              callbacks: {
                label: (context) => ` ${context.label}: ${context.parsed} case${context.parsed === 1 ? "" : "s"}`,
              },
            },
          },
        },
      });
    }

    if (pieTotal) pieTotal.textContent = total;
    if (pieLegend) {
      pieLegend.replaceChildren();
      data.forEach((district, index) => {
        const item = document.createElement("span");
        item.className = "district-pie-legend-item";
        const dot = document.createElement("i");
        dot.style.backgroundColor = colors[index];
        const name = document.createElement("b");
        name.textContent = district.label;
        const count = document.createElement("strong");
        count.textContent = district.count;
        item.append(dot, name, count);
        pieLegend.appendChild(item);
      });
    }
    if (pieUpdated && updatedAt) {
      const time = new Date(updatedAt);
      pieUpdated.textContent = `Updated ${time.toLocaleTimeString([], {hour: "2-digit", minute: "2-digit"})}`;
    }
  }

  drawPie(districts, districts.reduce((total, district) => total + (district.count || 0), 0), new Date().toISOString());

  async function refreshPie() {
    if (!liveUrl) return;
    try {
      const response = await fetch(liveUrl, {credentials: "same-origin", headers: {Accept: "application/json"}});
      if (!response.ok) return;
      const payload = await response.json();
      if (payload.districts && payload.districts.length) {
        drawPie(payload.districts, payload.total_cases, payload.updated_at);
      }
    } catch (error) {
      return;
    }
  }

  if (liveUrl) window.setInterval(refreshPie, 30000);
  document.addEventListener("rapid-response:system-ping", refreshPie);
}());
