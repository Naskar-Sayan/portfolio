document.addEventListener('DOMContentLoaded', function() {
    const photos = document.querySelectorAll('.photo-wrapper img');
    let currentIndex = 0;

    function showNextPhoto() {
        photos[currentIndex].classList.remove('active');
        currentIndex = (currentIndex + 1) % photos.length;
        photos[currentIndex].classList.add('active');
    }

    // Change photo every 3 seconds
    setInterval(showNextPhoto, 3000);
}); 