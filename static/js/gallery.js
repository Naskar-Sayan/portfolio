document.addEventListener('DOMContentLoaded', function() {
    const photoCards = document.querySelectorAll('.photo-card');
    const prevBtn = document.querySelector('.prev-btn');
    const nextBtn = document.querySelector('.next-btn');
    const dotsContainer = document.querySelector('.gallery-dots');
    
    let currentIndex = 0;
    
    // Create dots
    photoCards.forEach((_, index) => {
        const dot = document.createElement('div');
        dot.classList.add('dot');
        if (index === 0) dot.classList.add('active');
        dot.addEventListener('click', () => showPhoto(index));
        dotsContainer.appendChild(dot);
    });
    
    const dots = document.querySelectorAll('.dot');
    
    function showPhoto(index) {
        photoCards.forEach(card => card.classList.remove('active'));
        dots.forEach(dot => dot.classList.remove('active'));
        
        photoCards[index].classList.add('active');
        dots[index].classList.add('active');
        currentIndex = index;
    }
    
    function nextPhoto() {
        currentIndex = (currentIndex + 1) % photoCards.length;
        showPhoto(currentIndex);
    }
    
    function prevPhoto() {
        currentIndex = (currentIndex - 1 + photoCards.length) % photoCards.length;
        showPhoto(currentIndex);
    }
    
    prevBtn.addEventListener('click', prevPhoto);
    nextBtn.addEventListener('click', nextPhoto);
    
    // Auto slide every 5 seconds
    setInterval(nextPhoto, 5000);
}); 