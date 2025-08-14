document.addEventListener('DOMContentLoaded', function() {
    // DOM Elements
    const createPollBtn = document.getElementById('createPollBtn');
    const createPollEmptyBtn = document.getElementById('createPollEmptyBtn');
    const createPollModal = document.getElementById('createPollModal');
    const closeModal = document.getElementById('closeModal');
    const pollForm = document.getElementById('pollForm');
    const addOptionBtn = document.getElementById('addOptionBtn');
    const pollOptionsContainer = document.getElementById('pollOptionsContainer');
    const activePollsContainer = document.getElementById('activePollsContainer');
    const completedPollsContainer = document.getElementById('completedPollsContainer');
    const activeEmptyState = document.getElementById('activeEmptyState');
    const completedEmptyState = document.getElementById('completedEmptyState');
    const tabs = document.querySelectorAll('.tab');
    const tabContents = document.querySelectorAll('.tab-content');
    const toast = document.getElementById('toast');
    const toastMessage = document.getElementById('toastMessage');
    const voterModal = document.getElementById('voterModal');
    const voterForm = document.getElementById('voterForm');
    const closeVoterModal = document.getElementById('closeVoterModal');
    const voterNameInput = document.getElementById('voterName');
    const selectedPollIdInput = document.getElementById('selectedPollId');
    const selectedOptionIndexInput = document.getElementById('selectedOptionIndex');

    // Poll data - Firebase collections
    let polls = [];
    let voters = {};

    // Firebase functions
    async function loadPollsFromFirebase() {
        try {
            const pollsSnapshot = await db.collection('polls').get();
            polls = [];
            pollsSnapshot.forEach(doc => {
                const pollData = doc.data();
                // Convert Firestore timestamp to Date object
                if (pollData.deadline && pollData.deadline.toDate) {
                    pollData.deadline = pollData.deadline.toDate();
                }
                if (pollData.createdAt && pollData.createdAt.toDate) {
                    pollData.createdAt = pollData.createdAt.toDate();
                }
                polls.push({
                    id: doc.id,
                    ...pollData
                });
            });
            
            const votersSnapshot = await db.collection('voters').get();
            voters = {};
            votersSnapshot.forEach(doc => {
                voters[doc.id] = doc.data().voters || [];
            });
            
            renderPolls();
            updateEmptyStates();
        } catch (error) {
            console.error('Error loading polls:', error);
            showToast('Error al cargar las encuestas', 'error');
        }
    }

    async function savePollToFirebase(poll) {
        try {
            console.log('=== CREATING POLL ===');
            console.log('Poll to save:', poll);
            console.log('Poll options:', poll.options);
            
            const docRef = await db.collection('polls').add(poll);
            poll.id = docRef.id;
            polls.push(poll);
            renderPolls();
            updateEmptyStates();
            showToast('Encuesta creada exitosamente', 'success');
            console.log('Poll saved with ID:', poll.id);
        } catch (error) {
            console.error('Error saving poll:', error);
            showToast('Error al crear la encuesta', 'error');
        }
    }

    async function saveVoteToFirebase(pollId, voterName, optionIndex) {
        try {
            console.log('=== SAVING VOTE DEBUG ===');
            console.log('Saving vote:', { pollId, voterName, optionIndex });
            
            // Get fresh poll data from Firebase
            const pollRef = db.collection('polls').doc(pollId);
            const pollDoc = await pollRef.get();
            
            if (!pollDoc.exists) {
                throw new Error('Poll not found');
            }
            
            const pollData = pollDoc.data();
            console.log('Poll data from Firebase:', pollData);
            console.log('Poll options:', pollData.options);
            console.log('Option at index', optionIndex, ':', pollData.options[optionIndex]);
            
            // Validate optionIndex
            if (!pollData.options || optionIndex >= pollData.options.length || optionIndex < 0) {
                throw new Error(`Invalid option index. Index: ${optionIndex}, Options length: ${pollData.options ? pollData.options.length : 'undefined'}`);
            }
            
            // Check if the option exists
            if (!pollData.options[optionIndex]) {
                throw new Error(`Option at index ${optionIndex} does not exist`);
            }
            
            // Initialize votes property if it doesn't exist
            if (typeof pollData.options[optionIndex].votes !== 'number') {
                console.log('Initializing votes property for option', optionIndex);
                pollData.options[optionIndex].votes = 0;
            }
            
            console.log('Current votes for option', optionIndex, ':', pollData.options[optionIndex].votes);
            
            // Update vote count
            pollData.options[optionIndex].votes++;
            console.log('New votes count:', pollData.options[optionIndex].votes);
            
            // Update poll in Firebase
            await pollRef.update({
                options: pollData.options
            });

            // Update local polls array
            const localPoll = polls.find(p => p.id === pollId);
            if (localPoll) {
                localPoll.options = pollData.options;
            }

            // Update voters
            if (!voters[pollId]) {
                voters[pollId] = [];
            }
            voters[pollId].push(voterName);
            
            await db.collection('voters').doc(pollId).set({
                voters: voters[pollId]
            });

            renderPolls();
            showToast('¡Voto registrado exitosamente!', 'success');
            console.log('=== VOTE SAVED SUCCESSFULLY ===');
        } catch (error) {
            console.error('Error saving vote:', error);
            console.error('Error details:', error.message);
            showToast('Error al registrar el voto: ' + error.message, 'error');
        }
    }

    async function deletePollFromFirebase(pollId) {
        try {
            await db.collection('polls').doc(pollId).delete();
            await db.collection('voters').doc(pollId).delete();
            
            // Update local arrays
            polls = polls.filter(p => p.id !== pollId);
            delete voters[pollId];
            
            renderPolls();
            updateEmptyStates();
            showToast('Encuesta eliminada exitosamente', 'success');
        } catch (error) {
            console.error('Error deleting poll:', error);
            showToast('Error al eliminar la encuesta', 'error');
        }
    }

    // Render polls to the UI
    function renderPolls() {
        activePollsContainer.innerHTML = '';
        completedPollsContainer.innerHTML = '';

        const now = new Date();
        
        polls.forEach(poll => {
            // Cerrar automáticamente si la fecha límite pasó
            if (poll.status === "active" && poll.deadline) {
                const deadlineDate = new Date(poll.deadline + 'T23:59:59');
                if (now > deadlineDate) {
                    poll.status = "completed";
                    // Update status in Firebase
                    db.collection('polls').doc(poll.id).update({ status: "completed" });
                }
            }
            const pollElement = createPollElement(poll);
            if (poll.status === "active") {
                activePollsContainer.appendChild(pollElement);
            } else {
                completedPollsContainer.appendChild(pollElement);
            }
        });
    }

    // Create a poll element
    function createPollElement(poll) {
        const totalVotes = poll.options.reduce((sum, option) => sum + option.votes, 0);
        
        const pollElement = document.createElement('div');
        pollElement.className = 'card poll-card';
        pollElement.dataset.id = poll.id;
        
        let optionsHTML = '';
        poll.options.forEach((option, index) => {
            const percentage = totalVotes > 0 ? Math.round((option.votes / totalVotes) * 100) : 0;
            optionsHTML += `
                <div class="option-item">
                    <input type="radio" name="pollOption_${poll.id}" id="option_${poll.id}_${index}" class="option-radio" ${poll.status === "completed" ? "disabled" : ""}>
                    <label for="option_${poll.id}_${index}" class="option-text">${option.text}</label>
                    <span class="option-percentage">${percentage}%</span>
                    <div class="progress-bar">
                        <div class="progress-fill" style="width: ${percentage}%"></div>
                    </div>
                </div>
            `;
        });
        
        // Get voters for this poll
        const pollVoters = voters[poll.id] || [];
        const votersList = pollVoters.length > 0 ? 
            `<p><strong>Votantes:</strong> ${pollVoters.join(', ')}</p>` : 
            '';
        
        pollElement.innerHTML = `
            <div class="card-header">
                <h3 class="card-title">${poll.title}</h3>
                <div class="badge ${poll.status === "active" ? "badge-primary" : "badge-success"}">
                    ${poll.status === "active" ? "Activa" : "Completada"}
                </div>
                <button class="btn btn-danger delete-poll" style="float:right; margin-left:10px;" data-id="${poll.id}">
                    <i class="fas fa-trash"></i> Eliminar
                </button>
            </div>
            ${poll.description ? `<p>${poll.description}</p>` : ''}
            ${poll.deadline ? `<p><strong>Fecha límite:</strong> ${new Date(poll.deadline + 'T00:00:00').toLocaleDateString()}</p>` : ''}
            ${votersList}
            <div class="poll-options">
                ${optionsHTML}
            </div>
            <div class="poll-results">
                <div class="result-item">
                    <div class="result-header">
                        <span class="result-label">Total de Votos:</span>
                        <span class="result-value">${totalVotes}</span>
                    </div>
                </div>
            </div>
            ${poll.status === "active" ? `
                <button class="btn btn-primary submit-vote" style="width: 100%; margin-top: 1rem;" data-id="${poll.id}">
                    <i class="fas fa-vote-yea"></i> Votar
                </button>
            ` : ''}
        `;
        
        return pollElement;
    }

    // Update empty states
    function updateEmptyStates() {
        const activePolls = polls.filter(poll => poll.status === "active").length;
        const completedPolls = polls.filter(poll => poll.status === "completed").length;
        
        activeEmptyState.style.display = activePolls === 0 ? "block" : "none";
        completedEmptyState.style.display = completedPolls === 0 ? "block" : "none";
    }

    // Show toast notification
    function showToast(message, type = "success") {
        toast.className = `toast ${type}`;
        toastMessage.textContent = message;
        toast.classList.add('show');
        
        setTimeout(() => {
            toast.classList.remove('show');
        }, 3000);
    }

    // Event Listeners
    createPollBtn.addEventListener('click', () => {
        createPollModal.classList.add('active');
    });

    createPollEmptyBtn.addEventListener('click', () => {
        createPollModal.classList.add('active');
    });

    closeModal.addEventListener('click', () => {
        createPollModal.classList.remove('active');
    });

    closeVoterModal.addEventListener('click', () => {
        voterModal.classList.remove('active');
    });

    // Close modals when clicking outside
    [createPollModal, voterModal].forEach(modal => {
        modal.addEventListener('click', (e) => {
            if (e.target === modal) {
                modal.classList.remove('active');
            }
        });
    });

    // Add option input
    addOptionBtn.addEventListener('click', () => {
        const optionDiv = document.createElement('div');
        optionDiv.className = 'participant-item';
        optionDiv.style.marginBottom = '0.5rem';
        optionDiv.innerHTML = `
            <input type="text" class="form-control option-input" placeholder="Ingresa el texto de la opción" required>
            <button type="button" class="action-btn delete remove-option">
                <i class="fas fa-trash"></i>
            </button>
        `;
        pollOptionsContainer.appendChild(optionDiv);
        
        // Add event listener to the new remove button
        optionDiv.querySelector('.remove-option').addEventListener('click', () => {
            if (pollOptionsContainer.children.length > 2) {
                optionDiv.remove();
            } else {
                showToast("Una encuesta debe tener al menos 2 opciones", "error");
            }
        });
    });

    // Remove option input
    document.addEventListener('click', function(e) {
        if (e.target.classList.contains('remove-option')) {
            if (pollOptionsContainer.children.length > 2) {
                e.target.parentElement.remove();
            } else {
                showToast("Una encuesta debe tener al menos 2 opciones", "error");
            }
        }
    });

    // Delete poll event
    document.addEventListener('click', function(e) {
        if (e.target.classList.contains('delete-poll') || (e.target.closest && e.target.closest('.delete-poll'))) {
            const btn = e.target.classList.contains('delete-poll') ? e.target : e.target.closest('.delete-poll');
            const pollId = btn.dataset.id;
            deletePollFromFirebase(pollId);
        }
    });

    // Submit poll form
    pollForm.addEventListener('submit', function(e) {
        e.preventDefault();
        
        const title = document.getElementById('pollTitle').value.trim();
        const description = document.getElementById('pollDescription').value.trim();
        const deadline = document.getElementById('pollDeadline').value;
        
        // Get options
        const optionInputs = document.querySelectorAll('.option-input');
        const options = [];
        
        optionInputs.forEach(input => {
            if (input.value.trim()) {
                options.push({
                    text: input.value.trim(),
                    votes: 0
                });
            }
        });
        
        if (options.length < 2) {
            showToast("Por favor agrega al menos 2 opciones", "error");
            return;
        }
        
        // Create new poll
        const newPoll = {
            title,
            description,
            options,
            createdAt: new Date(),
            deadline: deadline,
            status: "active"
        };
        
        savePollToFirebase(newPoll);
        
        // Reset form
        pollForm.reset();
        pollOptionsContainer.innerHTML = `
            <div class="participant-item" style="margin-bottom: 0.5rem;">
                <input type="text" class="form-control option-input" placeholder="Ingresa el texto de la opción" required>
                <button type="button" class="action-btn delete remove-option">
                    <i class="fas fa-trash"></i>
                </button>
            </div>
            <div class="participant-item" style="margin-bottom: 0.5rem;">
                <input type="text" class="form-control option-input" placeholder="Ingresa el texto de la opción" required>
                <button type="button" class="action-btn delete remove-option">
                    <i class="fas fa-trash"></i>
                </button>
            </div>
        `;
        
        createPollModal.classList.remove('active');
    });

    // Tab switching
    tabs.forEach(tab => {
        tab.addEventListener('click', () => {
            tabs.forEach(t => t.classList.remove('active'));
            tabContents.forEach(c => c.classList.remove('active'));
            
            tab.classList.add('active');
            document.getElementById(`${tab.dataset.tab}-tab`).classList.add('active');
        });
    });

    // Prepare to submit vote
    document.addEventListener('click', function(e) {
        if (e.target.classList.contains('submit-vote') || e.target.closest('.submit-vote')) {
            const btn = e.target.classList.contains('submit-vote') ? e.target : e.target.closest('.submit-vote');
            const pollId = btn.dataset.id;
            const pollElement = document.querySelector(`[data-id="${pollId}"]`);
            const selectedOption = pollElement.querySelector('input[type="radio"]:checked');
            
            if (!selectedOption) {
                showToast("Por favor selecciona una opción", "error");
                return;
            }
            
            // Parse option index correctly - format is "option_pollId_index"
            const idParts = selectedOption.id.split('_');
            const optionIndex = parseInt(idParts[idParts.length - 1]); // Get the last part
            
            console.log('Selected option ID:', selectedOption.id);
            console.log('Parsed option index:', optionIndex);
            
            // Show voter modal
            selectedPollIdInput.value = pollId;
            selectedOptionIndexInput.value = optionIndex;
            voterModal.classList.add('active');
        }
    });

    // Submit voter form
    voterForm.addEventListener('submit', function(e) {
        e.preventDefault();
        
        const voterName = voterNameInput.value.trim();
        const pollId = selectedPollIdInput.value;
        const optionIndex = parseInt(selectedOptionIndexInput.value);
        
        if (!voterName) {
            showToast("Por favor ingresa tu nombre", "error");
            return;
        }
        
        // Check if voter already voted
        const pollVoters = voters[pollId] || [];
        if (pollVoters.includes(voterName)) {
            showToast("Ya has votado en esta encuesta", "error");
            return;
        }
        
        saveVoteToFirebase(pollId, voterName, optionIndex);
        
        voterForm.reset();
        voterModal.classList.remove('active');
    });

    // Load polls on page load
    loadPollsFromFirebase();
});
