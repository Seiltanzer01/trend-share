/* static/info/js/info.js */

/* Initialize Particles.js */
particlesJS("particles-js", {
    "particles": {
        "number": {
            "value": 200,
            "density": {
                "enable": true,
                "value_area": 800
            }
        },
        "color": {
            "value": "#f39c12"
        },
        "shape": {
            "type": "star",
            "stroke": {
                "width": 0,
                "color": "#000000"
            },
        },
        "opacity": {
            "value": 0.7,
            "random": true,
        },
        "size": {
            "value": 4,
            "random": true,
        },
        "line_linked": {
            "enable": true,
            "distance": 150,
            "color": "#f39c12",
            "opacity": 0.5,
            "width": 1
        },
        "move": {
            "enable": true,
            "speed": 6,
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
                "mode": "grab"
            },
            "onclick": {
                "enable": true,
                "mode": "push"
            },
        },
        "modes": {
            "grab": {
                "distance": 200,
                "line_linked": {
                    "opacity": 1
                }
            },
            "push": {
                "particles_nb": 5
            },
        }
    },
    "retina_detect": true
});

/* Initialize AOS (Animate On Scroll) */
AOS.init({
    duration: 1000,
    once: true
});

/* Initialize Swiper.js (If needed for any sliders) */
/* Uncomment and configure if using Swiper sliders */
/*
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
*/

/* Initialize Three.js for 3D Elements */
function initThreeJS() {
    const scene = new THREE.Scene();
    const camera = new THREE.PerspectiveCamera(75, window.innerWidth / 400, 0.1, 1000);
    const renderer = new THREE.WebGLRenderer({ alpha: true, antialias: true });
    renderer.setSize(window.innerWidth, 400);
    document.getElementById('threejs-scene').appendChild(renderer.domElement);

    // Create Torus Knot
    const geometry = new THREE.TorusKnotGeometry(10, 3, 100, 16);
    const material = new THREE.MeshStandardMaterial({ color: 0xf39c12, wireframe: true });
    const torusKnot = new THREE.Mesh(geometry, material);
    scene.add(torusKnot);

    // Add Lighting
    const ambientLight = new THREE.AmbientLight(0xffffff, 0.5);
    scene.add(ambientLight);

    const pointLight = new THREE.PointLight(0xffffff, 1);
    pointLight.position.set(50, 50, 50);
    scene.add(pointLight);

    camera.position.z = 30;

    // Animation Loop
    function animate() {
        requestAnimationFrame(animate);
        torusKnot.rotation.x += 0.01;
        torusKnot.rotation.y += 0.01;
        renderer.render(scene, camera);
    }

    animate();

    // Handle Window Resize
    window.addEventListener('resize', () => {
        camera.aspect = window.innerWidth / 400;
        camera.updateProjectionMatrix();
        renderer.setSize(window.innerWidth, 400);
    });
}

initThreeJS();

/* Initialize Lottie Animation */
var rocketAnimation = lottie.loadAnimation({
    container: document.getElementById('lottie-animation'),
    renderer: 'svg',
    loop: true,
    autoplay: true,
    path: '/static/info/animations/rocket.json' // Ensure this path is correct
});

/* Initialize Chart.js for Analytics */
const ctx = document.getElementById('analyticsChart').getContext('2d');
const analyticsChart = new Chart(ctx, {
    type: 'line',
    data: {
        labels: ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'],
        datasets: [{
            label: 'UJO Token Price',
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

/* Update Chart Data on Button Click */
document.getElementById('update-chart').addEventListener('click', () => {
    // Generate random data for demonstration
    const newData = [];
    for (let i = 0; i < 12; i++) {
        newData.push(Math.floor(Math.random() * 100) + 50);
    }
    analyticsChart.data.datasets[0].data = newData;
    analyticsChart.update();
    Swal.fire('Updated!', 'The chart data has been updated.', 'success');
});

/* GSAP Animations */
gsap.from(".logo-img", { duration: 2, y: -100, opacity: 0, ease: "bounce" });
gsap.from(".hero-content h1", { duration: 1.5, x: -300, opacity: 0, ease: "power2.out" });
gsap.from(".hero-content p", { duration: 1.5, x: 300, opacity: 0, ease: "power2.out", delay: 0.5 });
gsap.from(".interactive-btn", { duration: 1.5, scale: 0, opacity: 0, ease: "back.out(1.7)", delay: 1 });
gsap.from(".feature-card", { duration: 1, y: 50, opacity: 0, stagger: 0.2, ease: "power2.out" });
gsap.from(".subscription-card", { duration: 1, y: 50, opacity: 0, stagger: 0.2, ease: "power2.out" });

/* Initialize Mini-Game */
const gameCanvas = document.getElementById('gameCanvas');
const ctxGame = gameCanvas.getContext('2d');

let gameInterval;
let gameRunning = false;

// Simple Space Shooter Game
const player = {
    x: gameCanvas.width / 2 - 20,
    y: gameCanvas.height - 60,
    width: 40,
    height: 40,
    speed: 5,
    dx: 0
};

const bullets = [];
const enemies = [];
const enemySpeed = 2;
const bulletSpeed = 7;
const enemySpawnInterval = 1000; // Spawn enemy every 1 second
let score = 0;

// Draw Player
function drawPlayer() {
    ctxGame.fillStyle = '#f39c12';
    ctxGame.fillRect(player.x, player.y, player.width, player.height);
}

// Draw Bullets
function drawBullets() {
    ctxGame.fillStyle = '#2ecc71';
    bullets.forEach(bullet => {
        ctxGame.fillRect(bullet.x, bullet.y, bullet.width, bullet.height);
    });
}

// Draw Enemies
function drawEnemies() {
    ctxGame.fillStyle = '#e74c3c';
    enemies.forEach(enemy => {
        ctxGame.fillRect(enemy.x, enemy.y, enemy.width, enemy.height);
    });
}

// Draw Score
function drawScore() {
    ctxGame.fillStyle = '#ffffff';
    ctxGame.font = '20px Press Start 2P';
    ctxGame.fillText(`Score: ${score}`, 10, 30);
}

// Move Player
function movePlayer() {
    player.x += player.dx;

    // Boundary Detection
    if (player.x < 0) {
        player.x = 0;
    }
    if (player.x + player.width > gameCanvas.width) {
        player.x = gameCanvas.width - player.width;
    }
}

// Move Bullets
function moveBullets() {
    bullets.forEach((bullet, index) => {
        bullet.y -= bulletSpeed;
        // Remove bullets that go off-screen
        if (bullet.y + bullet.height < 0) {
            bullets.splice(index, 1);
        }
    });
}

// Move Enemies
function moveEnemies() {
    enemies.forEach((enemy, index) => {
        enemy.y += enemySpeed;
        // Remove enemies that go off-screen
        if (enemy.y > gameCanvas.height) {
            enemies.splice(index, 1);
            // Optionally, decrement score or handle life
        }
    });
}

// Collision Detection
function detectCollision() {
    enemies.forEach((enemy, eIndex) => {
        bullets.forEach((bullet, bIndex) => {
            if (
                bullet.x < enemy.x + enemy.width &&
                bullet.x + bullet.width > enemy.x &&
                bullet.y < enemy.y + enemy.height &&
                bullet.y + bullet.height > enemy.y
            ) {
                // Remove both enemy and bullet
                enemies.splice(eIndex, 1);
                bullets.splice(bIndex, 1);
                score += 10;
                // Increment score or handle accordingly
                Swal.fire({
                    title: 'Hit!',
                    text: 'You destroyed an enemy!',
                    icon: 'success',
                    timer: 1000,
                    showConfirmButton: false
                });
            }
        });
    });
}

// Spawn Enemies
function spawnEnemies() {
    const enemyWidth = 40;
    const enemyHeight = 40;
    const enemyX = Math.random() * (gameCanvas.width - enemyWidth);
    const enemyY = -enemyHeight;
    enemies.push({ x: enemyX, y: enemyY, width: enemyWidth, height: enemyHeight });
}

// Draw Game Elements
function draw() {
    ctxGame.clearRect(0, 0, gameCanvas.width, gameCanvas.height);
    drawPlayer();
    drawBullets();
    drawEnemies();
    drawScore();
}

// Update Game
function update() {
    movePlayer();
    moveBullets();
    moveEnemies();
    detectCollision();
    draw();
}

// Start Game
function startGame() {
    if (gameRunning) return;
    gameRunning = true;
    score = 0;
    gameInterval = setInterval(update, 30);
    setInterval(spawnEnemies, enemySpawnInterval);
    Swal.fire({
        title: 'Game Started!',
        text: 'Use Arrow Keys to Move and Space to Shoot.',
        icon: 'info',
        timer: 2000,
        showConfirmButton: false
    });
}

// Stop Game
function stopGame() {
    clearInterval(gameInterval);
    gameRunning = false;
    ctxGame.clearRect(0, 0, gameCanvas.width, gameCanvas.height);
    Swal.fire({
        title: 'Game Over!',
        text: `Your Score: ${score}`,
        icon: 'error',
        confirmButtonText: 'Play Again'
    }).then(() => {
        startGame();
    });
}

// Shoot Bullet
function shootBullet() {
    const bulletWidth = 5;
    const bulletHeight = 10;
    const bulletX = player.x + player.width / 2 - bulletWidth / 2;
    const bulletY = player.y;
    bullets.push({ x: bulletX, y: bulletY, width: bulletWidth, height: bulletHeight });
}

// Key Handlers
document.addEventListener('keydown', (e) => {
    if (e.code === 'ArrowRight') {
        player.dx = player.speed;
    } else if (e.code === 'ArrowLeft') {
        player.dx = -player.speed;
    } else if (e.code === 'Space') {
        shootBullet();
    }
});

document.addEventListener('keyup', (e) => {
    if (e.code === 'ArrowRight' || e.code === 'ArrowLeft') {
        player.dx = 0;
    }
});

// Start Game Button
document.getElementById('start-game').addEventListener('click', () => {
    startGame();
});

/* Interactive Buttons */

/* Basic Subscription Button */
document.getElementById('basic-subscription').addEventListener('click', () => {
    Swal.fire({
        title: 'Basic Subscription',
        text: 'Get access to basic DAO features for 1000 UJO.',
        icon: 'info',
        confirmButtonText: 'Proceed to Payment'
    }).then((result) => {
        if (result.isConfirmed) {
            window.location.href = "https://t.me/TrendShare_bot"; // Redirect to your Telegram bot or payment gateway
        }
    });
});

/* Premium Subscription Button */
document.getElementById('premium-subscription').addEventListener('click', () => {
    Swal.fire({
        title: 'Premium Subscription',
        text: 'Unlock full access to analytics, staking, and DAO governance for 5000 UJO.',
        icon: 'warning',
        confirmButtonText: 'Proceed to Payment'
    }).then((result) => {
        if (result.isConfirmed) {
            window.location.href = "https://t.me/TrendShare_bot"; // Redirect to your Telegram bot or payment gateway
        }
    });
});

/* DAO Button Interaction */
/* Assuming there's a button with id 'dao-button' */
document.getElementById('dao-button').addEventListener('click', () => {
    Swal.fire({
        title: 'Join the DAO',
        text: 'Become a part of the decentralized governance and vote on proposals.',
        icon: 'info',
        showCancelButton: true,
        confirmButtonText: 'Join DAO',
        cancelButtonText: 'Cancel'
    }).then((result) => {
        if (result.isConfirmed) {
            window.location.href = "https://t.me/TrendShare_bot"; // Redirect to your Telegram bot or DAO platform
        }
    });
});

/* Initialize Background Music (Optional) */
const backgroundMusic = new Audio('/static/info/audio/background-music.mp3'); // Add your audio file in the specified path
backgroundMusic.loop = true;
backgroundMusic.volume = 0.5;

// Play music on user interaction
document.body.addEventListener('click', () => {
    if (backgroundMusic.paused) {
        backgroundMusic.play();
    }
}, { once: true });

// Toggle Music Button
const musicToggleBtn = document.createElement('button');
musicToggleBtn.className = 'nes-btn is-primary music-toggle';
musicToggleBtn.innerText = '🔊';
musicToggleBtn.style.position = 'fixed';
musicToggleBtn.style.bottom = '20px';
musicToggleBtn.style.right = '20px';
musicToggleBtn.style.zIndex = '3000';
document.body.appendChild(musicToggleBtn);

musicToggleBtn.addEventListener('click', () => {
    if (backgroundMusic.paused) {
        backgroundMusic.play();
        musicToggleBtn.innerText = '🔊';
    } else {
        backgroundMusic.pause();
        musicToggleBtn.innerText = '🔇';
    }
});

/* Initialize Easter Egg */
let secretCode = '';
const secret = 'UJOTOKEN';

document.addEventListener('keydown', (e) => {
    secretCode += e.key.toUpperCase();
    if (secretCode.includes(secret)) {
        secretCode = '';
        Swal.fire({
            title: '🎉 Surprise!',
            text: 'You have unlocked the secret feature!',
            icon: 'success',
            showCancelButton: true,
            confirmButtonText: 'Redeem Reward',
            cancelButtonText: 'Close'
        }).then((result) => {
            if (result.isConfirmed) {
                // Handle reward redemption, e.g., redirect to Telegram bot
                window.location.href = "https://t.me/TrendShare_bot";
            }
        });
    }
    if (secretCode.length > secret.length) {
        secretCode = secretCode.slice(-secret.length);
    }
});

/* Interactive Elements Animations */
const buttons = document.querySelectorAll('.nes-btn');
buttons.forEach(button => {
    button.addEventListener('mouseenter', () => {
        gsap.to(button, { scale: 1.1, duration: 0.3, ease: "power2.out" });
    });
    button.addEventListener('mouseleave', () => {
        gsap.to(button, { scale: 1, duration: 0.3, ease: "power2.out" });
    });
});

/* Initialize Additional Three.js Scene Enhancements */
function enhanceThreeJSScene() {
    // Example: Add a rotating cube alongside the Torus Knot
    const scene = new THREE.Scene();
    const camera = new THREE.PerspectiveCamera(75, window.innerWidth / 400, 0.1, 1000);
    const renderer = new THREE.WebGLRenderer({ alpha: true, antialias: true });
    renderer.setSize(window.innerWidth, 400);
    document.getElementById('threejs-scene').appendChild(renderer.domElement);

    // Torus Knot
    const torusGeometry = new THREE.TorusKnotGeometry(10, 3, 100, 16);
    const torusMaterial = new THREE.MeshStandardMaterial({ color: 0xf39c12, wireframe: true });
    const torusKnot = new THREE.Mesh(torusGeometry, torusMaterial);
    scene.add(torusKnot);

    // Rotating Cube
    const cubeGeometry = new THREE.BoxGeometry();
    const cubeMaterial = new THREE.MeshStandardMaterial({ color: 0x2ecc71 });
    const cube = new THREE.Mesh(cubeGeometry, cubeMaterial);
    cube.position.x = 25;
    scene.add(cube);

    // Lighting
    const ambientLight = new THREE.AmbientLight(0xffffff, 0.5);
    scene.add(ambientLight);

    const pointLight = new THREE.PointLight(0xffffff, 1);
    pointLight.position.set(50, 50, 50);
    scene.add(pointLight);

    camera.position.z = 30;

    // Animation Loop
    function animate() {
        requestAnimationFrame(animate);
        torusKnot.rotation.x += 0.01;
        torusKnot.rotation.y += 0.01;
        cube.rotation.x += 0.02;
        cube.rotation.y += 0.02;
        renderer.render(scene, camera);
    }

    animate();

    // Handle Window Resize
    window.addEventListener('resize', () => {
        camera.aspect = window.innerWidth / 400;
        camera.updateProjectionMatrix();
        renderer.setSize(window.innerWidth, 400);
    });
}

enhanceThreeJSScene();

/* Initialize Lottie Animation */
var rocketAnimation = lottie.loadAnimation({
    container: document.getElementById('lottie-animation'),
    renderer: 'svg',
    loop: true,
    autoplay: true,
    path: '/static/info/animations/rocket.json' // Ensure this path is correct
});

/* Initialize Background Music */
const backgroundMusic = new Audio('/static/info/audio/background-music.mp3'); // Ensure the path is correct
backgroundMusic.loop = true;
backgroundMusic.volume = 0.5;

// Play music on user interaction
document.body.addEventListener('click', () => {
    if (backgroundMusic.paused) {
        backgroundMusic.play();
    }
}, { once: true });

// Toggle Music Button
const musicToggleBtn = document.createElement('button');
musicToggleBtn.className = 'nes-btn is-primary music-toggle';
musicToggleBtn.innerText = '🔊';
musicToggleBtn.style.position = 'fixed';
musicToggleBtn.style.bottom = '20px';
musicToggleBtn.style.right = '20px';
musicToggleBtn.style.zIndex = '3000';
musicToggleBtn.style.borderRadius = '50%';
musicToggleBtn.style.width = '50px';
musicToggleBtn.style.height = '50px';
musicToggleBtn.style.fontSize = '1.5em';
document.body.appendChild(musicToggleBtn);

musicToggleBtn.addEventListener('click', () => {
    if (backgroundMusic.paused) {
        backgroundMusic.play();
        musicToggleBtn.innerText = '🔊';
    } else {
        backgroundMusic.pause();
        musicToggleBtn.innerText = '🔇';
    }
});

/* Initialize Easter Egg */
let secretCode = '';
const secret = 'UJOTOKEN';

document.addEventListener('keydown', (e) => {
    secretCode += e.key.toUpperCase();
    if (secretCode.includes(secret)) {
        secretCode = '';
        Swal.fire({
            title: '🎉 Surprise!',
            text: 'You have unlocked the secret feature!',
            icon: 'success',
            showCancelButton: true,
            confirmButtonText: 'Redeem Reward',
            cancelButtonText: 'Close'
        }).then((result) => {
            if (result.isConfirmed) {
                // Handle reward redemption, e.g., redirect to Telegram bot
                window.location.href = "https://t.me/TrendShare_bot";
            }
        });
    }
    if (secretCode.length > secret.length) {
        secretCode = secretCode.slice(-secret.length);
    }
});

/* Interactive Elements Animations */
const buttons = document.querySelectorAll('.nes-btn');
buttons.forEach(button => {
    button.addEventListener('mouseenter', () => {
        gsap.to(button, { scale: 1.1, duration: 0.3, ease: "power2.out" });
    });
    button.addEventListener('mouseleave', () => {
        gsap.to(button, { scale: 1, duration: 0.3, ease: "power2.out" });
    });
});

/* Initialize Additional Three.js Scene Enhancements */
/* Already initialized above */

/* Initialize Lottie Animation */
/* Already initialized above */

/* Initialize Mini-Game */
/* Already implemented above */

/* Initialize Background Music */
/* Already implemented above */
