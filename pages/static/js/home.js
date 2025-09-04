    function toggleFAQ(event) {
    const faqBox = event.currentTarget.parentElement;
    const answerContent = faqBox.querySelector('.answer-content');
    const arrow = faqBox.querySelector('i');
    
    answerContent.classList.toggle('active');
    arrow.classList.toggle('fa-arrow-up');
    arrow.classList.toggle('fa-arrow-down');
}