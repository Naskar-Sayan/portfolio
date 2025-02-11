document.addEventListener('DOMContentLoaded', function() {
    const images = document.querySelectorAll('.profile-images img');
    const prevBtn = document.querySelector('.slider-nav .prev');
    const nextBtn = document.querySelector('.slider-nav .next');
    let currentIndex = 0;

    function showImage(index) {
        images.forEach(img => img.classList.remove('active'));
        images[index].classList.add('active');
    }

    function nextImage() {
        currentIndex = (currentIndex + 1) % images.length;
        showImage(currentIndex);
    }

    function prevImage() {
        currentIndex = (currentIndex - 1 + images.length) % images.length;
        showImage(currentIndex);
    }

    prevBtn.addEventListener('click', prevImage);
    nextBtn.addEventListener('click', nextImage);

    // Auto slide every 4 seconds
    setInterval(nextImage, 4000);
}); 