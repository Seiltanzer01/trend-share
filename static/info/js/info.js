/* static/info/js/info.js */

/* Инициализация Частиц Фона */
particlesJS("particles-js", {
    "particles": {
        "number": {
            "value": 80,
            "density": {
                "enable": true,
                "value_area": 800
            }
        },
        "color": {
            "value": "#f39c12"
        },
        "shape": {
            "type": "circle",
            "stroke": {
                "width": 0,
                "color": "#000000"
            },
        },
        "opacity": {
            "value": 0.5,
            "random": true,
        },
        "size": {
            "value": 3,
            "random": true,
        },
        "line_linked": {
            "enable": true,
            "distance": 150,
            "color": "#f39c12",
            "opacity": 0.4,
            "width": 1
        },
        "move": {
            "enable": true,
            "speed": 4,
            "direction": "none",
            "random": false,
            "straight": false,
            "out_mode": "out",
        }
    },
    "interactivity": {
        "detect_on": "canvas",
        "events": {
            "onhover": {
                "enable": true,
                "mode": "repulse"
            },
            "onclick": {
                "enable": true,
                "mode": "push"
            },
        },
        "modes": {
            "repulse": {
                "distance": 100,
                "duration": 0.4
            },
            "push": {
                "particles_nb": 4
            },
        }
    },
    "retina_detect": true
});

/* Инициализация AOS (Animate On Scroll) */
AOS.init({
    duration: 1000,
    once: true
});

/* Инициализация Swiper.js для Слайдера Функций */
const swiper = new Swiper('.swiper-container', {
    loop: true,
    autoplay: {
        delay: 7000,
    },
    pagination: {
        el: '.swiper-pagination',
        clickable: true,
    },
    navigation: {
        nextEl: '.swiper-button-next',
        prevEl: '.swiper-button-prev',
    },
});

/* Инициализация Three.js для 3D Элементов */
function initThreeJS() {
    const scene = new THREE.Scene();
    const camera = new THREE.PerspectiveCamera(75, window.innerWidth / 400, 0.1, 1000);
    const renderer = new THREE.WebGLRenderer({ alpha: true, antialias: true });
    renderer.setSize(window.innerWidth, 400);
    document.getElementById('threejs-scene').appendChild(renderer.domElement);

    const geometry = new THREE.TorusKnotGeometry(10, 3, 100, 16);
    const material = new THREE.MeshStandardMaterial({ color: 0xf39c12, wireframe: true });
    const torusKnot = new THREE.Mesh(geometry, material);
    scene.add(torusKnot);

    const light = new THREE.PointLight(0xffffff, 1);
    light.position.set(50, 50, 50);
    scene.add(light);

    camera.position.z = 30;

    function animate() {
        requestAnimationFrame(animate);
        torusKnot.rotation.x += 0.01;
        torusKnot.rotation.y += 0.01;
        renderer.render(scene, camera);
    }

    animate();

    window.addEventListener('resize', () => {
        camera.aspect = window.innerWidth / 400;
        camera.updateProjectionMatrix();
        renderer.setSize(window.innerWidth, 400);
    });
}

initThreeJS();

/* Обработчики Кнопок Подписки */
document.getElementById('basic-subscription').addEventListener('click', () => {
    Swal.fire({
        title: 'Базовая Подписка',
        text: 'Вы получите доступ к основным функциям DAO за 1000 UJO.',
        icon: 'info',
        confirmButtonText: 'Перейти к оплате'
    }).then((result) => {
        if (result.isConfirmed) {
            window.location.href = "https://t.me/TrendShare_bot"; // Ссылка на бота или оплату
        }
    });
});

document.getElementById('premium-subscription').addEventListener('click', () => {
    Swal.fire({
        title: 'Премиум Подписка',
        text: 'Получите полный доступ к аналитике, стейкингу и управлению DAO за 5000 UJO.',
        icon: 'warning',
        confirmButtonText: 'Перейти к оплате'
    }).then((result) => {
        if (result.isConfirmed) {
            window.location.href = "https://t.me/TrendShare_bot"; // Ссылка на бота или оплату
        }
    });
});

/* Обработчик Кнопки Присоединиться в DAO */
document.getElementById('dao-button').addEventListener('click', () => {
    Swal.fire({
        title: 'Присоединиться к DAO',
        text: 'Стать участником децентрализованного управления и голосовать за предложения.',
        icon: 'info',
        showCancelButton: true,
        confirmButtonText: 'Присоединиться',
        cancelButtonText: 'Отмена'
    }).then((result) => {
        if (result.isConfirmed) {
            window.location.href = "https://t.me/TrendShare_bot"; // Ссылка на бота или другое действие
        }
    });
});

/* Инициализация Chart.js для Аналитики */
const ctx = document.getElementById('analyticsChart').getContext('2d');
const analyticsChart = new Chart(ctx, {
    type: 'line',
    data: {
        labels: ['Янв', 'Фев', 'Мар', 'Апр', 'Май', 'Июн', 'Июл', 'Авг', 'Сен', 'Окт', 'Ноя', 'Дек'],
        datasets: [{
            label: 'Цена UJO токена',
            data: [50, 60, 55, 70, 65, 80, 75, 90, 85, 100, 95, 110],
            backgroundColor: 'rgba(243, 156, 18, 0.2)',
            borderColor: '#f39c12',
            borderWidth: 2,
            fill: true,
            tension: 0.4,
            pointRadius: 5,
            pointBackgroundColor: '#f39c12'
        }]
    },
    options: {
        responsive: true,
        plugins: {
            legend: {
                labels: {
                    color: '#ffffff'
                }
            },
            tooltip: {
                enabled: true,
                backgroundColor: '#f39c12',
                titleColor: '#ffffff',
                bodyColor: '#ffffff',
                borderColor: '#ffffff',
                borderWidth: 1
            }
        },
        scales: {
            x: {
                ticks: {
                    color: '#ffffff'
                },
                grid: {
                    color: '#444444'
                }
            },
            y: {
                ticks: {
                    color: '#ffffff'
                },
                grid: {
                    color: '#444444'
                },
                beginAtZero: true
            }
        }
    }
});

/* Обновление Данных Графика */
document.getElementById('update-chart').addEventListener('click', () => {
    // Генерация случайных данных для примера
    const newData = [];
    for (let i = 0; i < 12; i++) {
        newData.push(Math.floor(Math.random() * 100) + 50);
    }
    analyticsChart.data.datasets[0].data = newData;
    analyticsChart.update();
    Swal.fire('Обновлено!', 'Данные графика были обновлены.', 'success');
});

/* Инициализация GSAP для Дополнительных Анимаций */
gsap.from(".logo-img", { duration: 2, y: -100, opacity: 0, ease: "bounce" });
gsap.from(".hero-content h1", { duration: 1.5, x: -300, opacity: 0, ease: "power2.out" });
gsap.from(".hero-content p", { duration: 1.5, x: 300, opacity: 0, ease: "power2.out", delay: 0.5 });
gsap.from(".interactive-btn", { duration: 1.5, scale: 0, opacity: 0, ease: "back.out(1.7)", delay: 1 });

/* Обработчики Кнопок для Открытия Видео Модала */
document.querySelectorAll('.open-video-btn').forEach(button => {
    button.addEventListener('click', () => {
        const modal = document.getElementById('videoModal');
        const iframe = document.getElementById('videoIframe');
        iframe.src = 'https://www.youtube.com/embed/VIDEO_ID?autoplay=1'; // Замените VIDEO_ID на ID вашего видео
        modal.style.display = 'block';
    });
});

/* Обработчик Закрытия Видео Модала */
document.querySelector('.close-video').addEventListener('click', () => {
    const modal = document.getElementById('videoModal');
    const iframe = document.getElementById('videoIframe');
    iframe.src = '';
    modal.style.display = 'none';
});

/* Закрытие Модального Окна При Клиниге Вне Его */
window.addEventListener('click', (event) => {
    const modal = document.getElementById('videoModal');
    if (event.target == modal) {
        const iframe = document.getElementById('videoIframe');
        iframe.src = '';
        modal.style.display = 'none';
    }
});
