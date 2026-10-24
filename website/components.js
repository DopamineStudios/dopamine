const bgHTML = `
  <div class="bg-gradient"></div>
  <div class="bg-noise"></div>
`;

const navHTML = `
<nav id="main-nav">
  <div class="container">
    <div class="logo">
      <img src="dopamineanimated.gif" alt="Logo" class="logo-img">
      DOPAMINE
    </div>

    <button class="menu-toggle" aria-label="Toggle menu">
      <span></span>
      <span></span>
      <span></span>
    </button>

    <ul class="nav-links">
      <li><a href="index.html">Home</a></li>
      <li><a href="invite.html">Invite</a></li>
      <li><a href="changelog.html">Changelog</a></li>
      <li><a href="https://status.dopaminestudios.in/">Bot Status</a></li>
      <li><a href="https://top.gg/bot/1411266382380924938">Vote</a></li>
      <div class="nav-underline"></div> 
    </ul>
  </div>
</nav>
`;

const footerHTML = `
<footer>
  <div class="container">
    <div class="footer-grid">
      <div class="footer-brand">
        <span class="container-headerr"><h3>DOPAMINE</h3></span>
        <p>A <strong>Dopamine Studios</strong> project.<br>Made in India. 🇮🇳</p>
      </div>

      <div class="footer-column">
        <h4>Resources</h4>
        <ul class="footer-links">
          <li><a href="./privacypolicy.html">Privacy Policy</a></li>
          <li><a href="./tos.html">Terms of Service</a></li>
          <li><a href="https://github.com/likerofturtles/dopamine" target="_blank">Source Code</a></li>
          <li><a href="https://discord.gg/PW7YN5xNBB" target="_blank">Support Server</a></li>
          <li><a href="mailto:hey@dopaminestudios.in">Contact Us</a></li>
        </ul>
      </div>

      <div class="footer-column">
        <h4>More From Us</h4>
        <ul class="footer-links">
          <li><a href="https://twilight.dopaminestudios.in/" target="_blank">Twilight</a></li>
          <li><a href="https://stealamoji.dopaminestudios.in/" target="_blank" rel="noopener">Steal-a-moji</a></li>
          <li><a href="https://pokempanion.dopaminestudios.in/" target="_blank" rel="noopener">Pokémpanion</a></li>
          <li><a href="https://beacon.dopaminestudios.in/" target="_blank">Beacon</a></li>
          <li><a href="https://blog.dopaminestudios.in/" target="_blank">Dopamine Blog</a></li>
        </ul>
      </div>
    </div>

    <div class="footer-bottom">
      <p>&copy; 2026 Dopamine Studios. All rights reserved.</p>
      <p>Contact: <a href="mailto:hey@dopaminestudios.in" style="color: inherit; text-decoration: none;">hey@dopaminestudios.in</a></p>
    </div>
  </div>
</footer>
`;

function initializeComponents() {
    document.body.insertAdjacentHTML('afterbegin', bgHTML);

    document.body.insertAdjacentHTML('afterbegin', navHTML);

    document.body.insertAdjacentHTML('beforeend', footerHTML);

    const nav = document.getElementById('main-nav');
    const navLinks = document.querySelector('.nav-links');
    const menuToggle = document.querySelector('.menu-toggle');
    const underline = document.querySelector('.nav-underline');
    const allLinks = document.querySelectorAll('.nav-links a');

    const normalize = (path) => {
        if (!path) return "";
        return path.split("/").pop().replace(".html", "").replace("/", "") || "index";
    };

    let currentPath = normalize(window.location.pathname);
    if (currentPath === 'version') {
        currentPath = 'changelog';
    }
    let lastScrollY = window.scrollY;

    function moveUnderline(element, instant = false) {
        if (!element || !underline) return;

        if (instant) {
            underline.classList.add('no-transition');
        } else {
            underline.classList.remove('no-transition');
        }

        underline.style.width = `${element.offsetWidth}px`;
        underline.style.left = `${element.offsetLeft}px`;
        underline.style.opacity = "1";

        if (instant) {
            void underline.offsetWidth;
            underline.classList.remove('no-transition');
        }
    }

    allLinks.forEach(link => {
        const href = link.getAttribute('href') || '';
        const isInternal = href.includes('.html') || !href.startsWith('http');
        const linkPath = isInternal ? normalize(href) : null;

        if (isInternal && linkPath === currentPath) {
            link.classList.add('active-link');
            setTimeout(() => moveUnderline(link, true), 50);
        }

        link.addEventListener('mouseenter', () => moveUnderline(link));
        link.addEventListener('click', () => {
            allLinks.forEach(l => l.classList.remove('active-link'));
            link.classList.add('active-link');
            moveUnderline(link);
        });
    });

    if (navLinks) {
        navLinks.addEventListener('mouseleave', () => {
            const activeLink = document.querySelector('.active-link');
            if (activeLink) moveUnderline(activeLink);
        });
    }

    if (menuToggle && navLinks) {
        menuToggle.addEventListener('click', () => {
            menuToggle.classList.toggle('active');
            navLinks.classList.toggle('active');
        });

        navLinks.querySelectorAll('a').forEach(link => {
            link.addEventListener('click', () => {
                menuToggle.classList.remove('active');
                navLinks.classList.remove('active');
            });
        });
    }

    window.addEventListener('scroll', () => {
        const currentScrollY = window.scrollY;
        if (currentScrollY > lastScrollY && currentScrollY > 100) {
            nav.classList.add('nav-hidden');
        } else {
            nav.classList.remove('nav-hidden');
        }
        nav.classList.toggle('nav-scrolled', currentScrollY > 10);
        lastScrollY = currentScrollY;
    });
}

document.addEventListener('DOMContentLoaded', initializeComponents);
