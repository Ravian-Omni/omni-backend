import time
from typing import Dict, List, Optional, Any, Tuple
from collections import defaultdict


class OmniStorage:
    """
    A simple manager for OMNI chat and capability chats that automatically
    maintains the sequential flow of messages without requiring explicit iteration flags.
    Also tracks the most recently updated capabilities.
    """
    
    def __init__(self):
        # Main chat messages
        self.main_chat_messages = []
        
        # Store sequential messages for each capability
        # Structure: capabilities[capability_name] = [list of all messages in sequence]
        self.capabilities = defaultdict(list)
        
        # Store iteration boundaries for each capability
        # Structure: capability_iterations[capability_name] = [list of message indices that start new iterations]
        self.capability_iterations = defaultdict(list)
        
        # Cache of latest agent messages for quick access
        # Structure: _agent_latest_messages[capability_name][agent_name] = message
        self._agent_latest_messages = defaultdict(dict)
        
        # Track recently updated capabilities with timestamps
        # Structure: [(capability_name, timestamp), ...] ordered by most recent first
        self.recently_updated_capabilities = []
        
        # Store the last updated timestamp for each capability
        # Structure: capability_last_updated[capability_name] = timestamp
        self.capability_last_updated = {}
    
    def add_main_message(self, role: str, agent_name: str, content: Any, **kwargs) -> Dict:
        """
        Add a message to the main OMNI chat.
        
        Args:
            role: Role of the agent (e.g., "assistant", "user", "system")
            agent_name: Name of the agent
            content: Message content
            **kwargs: Additional message attributes
            
        Returns:
            The message dictionary
        """
        message = {
            "role": role,
            "name": agent_name,
            "content": content,
            "timestamp": time.time(),
            **kwargs
        }
        
        self.main_chat_messages.append(message)
        return message
    
    def add_capability_message(self, capability_name: str, role: str, agent_name: str, 
                               content: Any, new_iteration: bool = False, **kwargs) -> Dict:
        """
        Add a message to a capability chat.
        
        Args:
            capability_name: Name of the capability (e.g., "application_developer")
            role: Role of the agent (e.g., "assistant", "user", "system")
            agent_name: Name of the agent
            content: Message content
            new_iteration: If True, marks this message as the start of a new iteration
            **kwargs: Additional message attributes
            
        Returns:
            The message dictionary
        """
        # Get current timestamp
        current_time = time.time()
        
        # Create the message
        message = {
            "role": role,
            "name": agent_name,
            "content": content,
            "timestamp": current_time,
            "capability": capability_name,  # Store the capability name in the message
            **kwargs
        }
        
        # If this is a new iteration, record the boundary
        if new_iteration or not self.capabilities[capability_name]:
            # The index will be the length of the current capability messages list
            self.capability_iterations[capability_name].append(len(self.capabilities[capability_name]))
        
        # Add the message to the capability's sequential message list
        self.capabilities[capability_name].append(message)
        
        # Update latest message cache for this agent
        self._agent_latest_messages[capability_name][agent_name] = message
        
        # Update the recently updated capabilities tracking
        self._update_recently_updated_capability(capability_name, current_time)
        
        return message
        
    def _update_recently_updated_capability(self, capability_name: str, timestamp: float) -> None:
        """
        Update the tracking of recently updated capabilities.
        
        Args:
            capability_name: Name of the capability that was updated
            timestamp: Timestamp of the update
        """
        # Update the last updated timestamp for this capability
        self.capability_last_updated[capability_name] = timestamp
        
        # Remove this capability from the recently updated list if it exists
        self.recently_updated_capabilities = [
            (cap, ts) for cap, ts in self.recently_updated_capabilities if cap != capability_name
        ]
        
        # Add this capability as the most recently updated
        self.recently_updated_capabilities.insert(0, (capability_name, timestamp))
        
    def get_most_recently_updated_capability(self) -> Optional[str]:
        """
        Get the name of the most recently updated capability.
        
        Returns:
            Name of the most recently updated capability, or None if no capabilities have been updated
        """
        if not self.recently_updated_capabilities:
            return None
        return self.recently_updated_capabilities[0][0]
        
    def get_recently_updated_capabilities(self, count: int = 5) -> List[str]:
        """
        Get the names of the most recently updated capabilities.
        
        Args:
            count: Maximum number of capabilities to return
            
        Returns:
            List of capability names ordered by most recently updated first
        """
        return [cap for cap, _ in self.recently_updated_capabilities[:count]]
        
    def get_last_agent_message_from_most_recent_capability(self, agent_name: str) -> Optional[Dict]:
        """
        Get the latest message from a specific agent in the most recently updated capability.
        
        Args:
            agent_name: Name of the agent
            
        Returns:
            Latest message dictionary or None if not found
        """
        capability_name = self.get_most_recently_updated_capability()
        if not capability_name:
            return None
        
        return self.get_latest_agent_message(capability_name, agent_name)
        
    def get_specific_agent_message_from_capabilities(self, agent_name: str, capabilities: Optional[List[str]] = None) -> Dict[str, Dict]:
        """
        Get the latest message from a specific agent across multiple capabilities.
        
        Args:
            agent_name: Name of the agent
            capabilities: List of capability names to check (None for all capabilities)
            
        Returns:
            Dictionary mapping capability names to the agent's latest message in that capability
        """
        result = {}
        
        # If no capabilities specified, use all capabilities
        if capabilities is None:
            capabilities = self.capabilities.keys()
        
        for capability_name in capabilities:
            latest_message = self.get_latest_agent_message(capability_name, agent_name)
            if latest_message:
                result[capability_name] = latest_message
        
        return result
        
    def get_ordered_agent_messages(self, agent_name: str) -> List[Tuple[str, Dict]]:
        """
        Get all messages from a specific agent across all capabilities,
        ordered by timestamp (most recent first).
        
        Args:
            agent_name: Name of the agent
            
        Returns:
            List of (capability_name, message) tuples ordered by timestamp
        """
        all_messages = []
        
        # Collect all messages from this agent across all capabilities
        for capability_name in self.capabilities:
            for message in self.capabilities[capability_name]:
                if message["name"] == agent_name:
                    all_messages.append((capability_name, message))
        
        # Sort by timestamp, most recent first
        all_messages.sort(key=lambda x: x[1]["timestamp"], reverse=True)
        
        return all_messages
    
    def get_main_chat_messages(self) -> List[Dict]:
        """Get all messages from the main chat."""
        return self.main_chat_messages
    
    def get_capability_iterations(self, capability_name: str) -> List[int]:
        """
        Get the list of iteration boundary indices for a capability.
        
        Args:
            capability_name: Name of the capability
            
        Returns:
            List of message indices that mark the start of iterations
        """
        return self.capability_iterations.get(capability_name, [])
    
    def get_current_iteration_index(self, capability_name: str) -> int:
        """
        Get the index of the current/latest iteration for a capability.
        
        Args:
            capability_name: Name of the capability
            
        Returns:
            Index of the current iteration (0 if no iterations exist)
        """
        iterations = self.capability_iterations.get(capability_name, [0])
        return len(iterations) - 1
    
    def get_all_capability_messages(self, capability_name: str) -> List[Dict]:
        """
        Get all messages from a capability chat.
        
        Args:
            capability_name: Name of the capability
            
        Returns:
            List of all message dictionaries for the capability
        """
        return self.capabilities.get(capability_name, [])
    
    def get_iteration_messages(self, capability_name: str, iteration_index: Optional[int] = None) -> List[Dict]:
        """
        Get messages from a specific iteration of a capability chat.
        
        Args:
            capability_name: Name of the capability
            iteration_index: Index of the iteration (None for current/latest iteration)
            
        Returns:
            List of message dictionaries for the specified iteration
        """
        if capability_name not in self.capabilities:
            return []
        
        if iteration_index is None:
            iteration_index = self.get_current_iteration_index(capability_name)
        
        if iteration_index < 0 or iteration_index >= len(self.capability_iterations[capability_name]):
            return []
        
        # Get the start index for this iteration
        start_idx = self.capability_iterations[capability_name][iteration_index]
        
        # Get the end index (start of next iteration or end of all messages)
        if iteration_index + 1 < len(self.capability_iterations[capability_name]):
            end_idx = self.capability_iterations[capability_name][iteration_index + 1]
        else:
            end_idx = len(self.capabilities[capability_name])
        
        # Return the slice of messages for this iteration
        return self.capabilities[capability_name][start_idx:end_idx]
    
    def get_latest_agent_message(self, capability_name: str, agent_name: str) -> Optional[Dict]:
        """
        Get the latest message from a specific agent in a capability.
        
        Args:
            capability_name: Name of the capability
            agent_name: Name of the agent
            
        Returns:
            Latest message dictionary or None if not found
        """
        # Check if we have a cached latest message
        if capability_name in self._agent_latest_messages and agent_name in self._agent_latest_messages[capability_name]:
            return self._agent_latest_messages[capability_name][agent_name]
        
        # If not in cache, find it manually
        if capability_name not in self.capabilities:
            return None
        
        # Find the latest message from this agent by scanning from the end
        messages = self.capabilities[capability_name]
        for message in reversed(messages):
            if message["name"] == agent_name:
                # Update cache and return the message
                self._agent_latest_messages[capability_name][agent_name] = message
                return message
        
        return None
    
    def get_latest_iteration_agent_messages(self, capability_name: str, agent_name: str) -> Optional[Dict]:
        """
        Get the latest message from a specific agent in the current iteration of a capability.
        
        Args:
            capability_name: Name of the capability
            agent_name: Name of the agent
            
        Returns:
            Latest message dictionary from current iteration or None if not found
        """
        # Get the current iteration messages
        current_iteration_messages = self.get_iteration_messages(capability_name)
        
        # Find the latest message from this agent in the current iteration
        for message in reversed(current_iteration_messages):
            if message["name"] == agent_name:
                return message
        
        return None
    
    def get_all_latest_agent_messages(self, capability_name: str) -> Dict[str, Dict]:
        """
        Get the latest message from each agent in a capability.
        
        Args:
            capability_name: Name of the capability
            
        Returns:
            Dictionary mapping agent names to their latest messages
        """
        if capability_name not in self.capabilities:
            return {}
        
        messages = self.capabilities[capability_name]
        
        # Dictionary to store the latest message for each agent
        latest_messages = {}
        
        # Find the latest message for each agent by scanning from the end
        for message in reversed(messages):
            agent_name = message["name"]
            if agent_name not in latest_messages:
                latest_messages[agent_name] = message
        
        return latest_messages
    
    def get_all_latest_iteration_agent_messages(self, capability_name: str) -> Dict[str, Dict]:
        """
        Get the latest message from each agent in the current iteration of a capability.
        
        Args:
            capability_name: Name of the capability
            
        Returns:
            Dictionary mapping agent names to their latest messages in current iteration
        """
        # Get the current iteration messages
        current_iteration_messages = self.get_iteration_messages(capability_name)
        
        # Dictionary to store the latest message for each agent
        latest_messages = {}
        
        # Find the latest message for each agent in the current iteration
        for message in reversed(current_iteration_messages):
            agent_name = message["name"]
            if agent_name not in latest_messages:
                latest_messages[agent_name] = message
        
        return latest_messages
    
    def start_new_iteration(self, capability_name: str) -> int:
        """
        Explicitly start a new iteration for a capability.
        The next message added will be the first in the new iteration.
        
        Args:
            capability_name: Name of the capability
            
        Returns:
            Index of the new iteration
        """
        # The new iteration will start at the current length of messages
        next_msg_index = len(self.capabilities[capability_name])
        
        # If this would create a duplicate iteration boundary, don't do it
        if self.capability_iterations.get(capability_name, [-1])[-1] == next_msg_index:
            return len(self.capability_iterations[capability_name]) - 1
        
        # Add the new iteration boundary
        self.capability_iterations[capability_name].append(next_msg_index)
        return len(self.capability_iterations[capability_name]) - 1
    
    def search_messages(self, query: str, capability_name: Optional[str] = None, 
                       agent_name: Optional[str] = None) -> List[Dict]:
        """
        Search for messages containing the query.
        
        Args:
            query: Text to search for
            capability_name: Optional capability to limit the search to
            agent_name: Optional agent name to limit the search to
            
        Returns:
            List of message dictionaries that match the search criteria
        """
        results = []
        
        # Search in main chat if no specific capability is requested
        if capability_name is None or capability_name == "OMNI":
            for message in self.main_chat_messages:
                if (agent_name is None or message["name"] == agent_name) and query.lower() in str(message["content"]).lower():
                    results.append({**message, "source": "OMNI"})
        
        # Search in capabilities
        capabilities_to_search = [capability_name] if capability_name else self.capabilities.keys()
        
        for cap_name in capabilities_to_search:
            if cap_name in self.capabilities:
                # Get iteration boundaries for this capability
                iterations = self.capability_iterations.get(cap_name, [0])
                
                for i, msg_idx in enumerate(iterations):
                    # Determine end index for this iteration
                    end_idx = iterations[i+1] if i+1 < len(iterations) else len(self.capabilities[cap_name])
                    
                    # Check messages in this iteration
                    for idx in range(msg_idx, end_idx):
                        message = self.capabilities[cap_name][idx]
                        if (agent_name is None or message["name"] == agent_name) and query.lower() in str(message["content"]).lower():
                            results.append({**message, "source": f"{cap_name}:iteration_{i}"})
        
        return results
    
    def get_capability_names(self) -> List[str]:
        """Get a list of all capability names."""
        return list(self.capabilities.keys())
    
    def get_capability_agent_names(self, capability_name: str) -> List[str]:
        """
        Get a list of all agent names that have participated in a capability.
        
        Args:
            capability_name: Name of the capability
            
        Returns:
            List of agent names
        """
        if capability_name not in self.capabilities:
            return []
        
        # Collect unique agent names
        agent_names = set()
        for msg in self.capabilities[capability_name]:
            agent_names.add(msg["name"])
        
        return list(agent_names)
    
    def get_capability_summary(self, capability_name: str) -> Dict:
        """
        Get a summary of a capability.
        
        Args:
            capability_name: Name of the capability
            
        Returns:
            Dictionary with capability summary information
        """
        if capability_name not in self.capabilities:
            return {"name": capability_name, "exists": False}
        
        messages = self.capabilities[capability_name]
        iterations = self.capability_iterations.get(capability_name, [0])
        
        agent_set = set()
        for msg in messages:
            agent_set.add(msg["name"])
        
        return {
            "name": capability_name,
            "exists": True,
            "total_messages": len(messages),
            "iterations": len(iterations),
            "current_iteration": len(iterations) - 1,
            "agents": list(agent_set)
        }



omni_storage = OmniStorage()

# # Example usage
# if __name__ == "__main__":
#     # Initialize the manager
#     chat_manager = OmniChatManager()
    
#     # Add messages to main chat
#     chat_manager.add_main_message("user", "user123", "I need help with my application")
#     chat_manager.add_main_message("system", "system", "Activating application_developer capability")
    
#     # Add messages to capability chats - first message automatically starts a new iteration
#     chat_manager.add_capability_message("application_developer", "assistant", "dev_assistant", 
#                                        "I'll help you develop your application")
#     chat_manager.add_capability_message("application_developer", "assistant", "code_reviewer", 
#                                        "I'll review your code")
    
#     # Add messages to another capability
#     chat_manager.add_capability_message("email_manager", "assistant", "email_assistant", 
#                                       "I can help you send emails")
    
#     # Add more messages to the first capability
#     chat_manager.add_capability_message("application_developer", "user", "user123", 
#                                        "Can you create a login form?")
#     chat_manager.add_capability_message("application_developer", "assistant", "dev_assistant", 
#                                        "Here's a simple login form implementation")
    
#     # Most recently updated capability should be application_developer
#     recent_capability = chat_manager.get_most_recently_updated_capability()
#     print(f"Most recently updated capability: {recent_capability}")
    
#     # Get dev_assistant message from most recently updated capability
#     dev_message = chat_manager.get_last_agent_message_from_most_recent_capability("dev_assistant")
#     print(f"Latest message from dev_assistant in most recent capability: {dev_message['content']}")
    
#     # Sleep a bit to ensure timestamps are different
#     time.sleep(0.1)
    
#     # Now update email_manager
#     chat_manager.add_capability_message("email_manager", "assistant", "email_assistant", 
#                                       "I've drafted an email template for you")
    
#     # Most recently updated capability should now be email_manager
#     recent_capability = chat_manager.get_most_recently_updated_capability()
#     print(f"Most recently updated capability is now: {recent_capability}")
    
#     # Get email_assistant message from most recently updated capability
#     email_message = chat_manager.get_last_agent_message_from_most_recent_capability("email_assistant")
#     print(f"Latest message from email_assistant in most recent capability: {email_message['content']}")
    
#     # Get all messages from dev_assistant across all capabilities, ordered by timestamp
#     dev_messages = chat_manager.get_ordered_agent_messages("dev_assistant")
#     print("\nAll dev_assistant messages by recency:")
#     for cap, msg in dev_messages:
#         print(f"[{cap}] {msg['content']}")
    
#     # Get the recently updated capabilities (up to 3)
#     recent_capabilities = chat_manager.get_recently_updated_capabilities(count=3)
#     print(f"\nRecently updated capabilities: {recent_capabilities}")
    
#     # Get specific agent messages across multiple capabilities
#     specific_messages = chat_manager.get_specific_agent_message_from_capabilities("dev_assistant")
#     print("\nLatest dev_assistant messages by capability:")
#     for cap, msg in specific_messages.items():
#         print(f"[{cap}] {msg['content']}")

# Example usage
# if __name__ == "__main__":
#     # Initialize the manager
#     chat_manager = OmniStorage()
    
#     # Add messages to main chat
#     chat_manager.add_main_message("user", "user123", "I need help with my application")
#     chat_manager.add_main_message("system", "system", "Activating application_developer capability")
    
#     # Add messages to capability chats - first message automatically starts a new iteration
#     chat_manager.add_capability_message("application_developer", "assistant", "dev_assistant", 
#                                        "I'll help you develop your application")
#     chat_manager.add_capability_message("application_developer", "assistant", "code_reviewer", 
#                                        "I'll review your code")
    
#     # Add more messages
#     chat_manager.add_capability_message("application_developer", "user", "user123", 
#                                        "Can you create a login form?")
#     chat_manager.add_capability_message("application_developer", "assistant", "dev_assistant", 
#                                        "Here's a simple login form implementation")
    
#     # Explicitly start a new iteration (optional)
#     chat_manager.start_new_iteration("application_developer")
    
#     # Add messages to the new iteration
#     chat_manager.add_capability_message("application_developer", "user", "user123", 
#                                        "Now I need to add authentication")
#     chat_manager.add_capability_message("application_developer", "assistant", "dev_assistant", 
#                                        "Let's implement authentication")
    
#     # Add message to another capability (automatically starts first iteration)
#     chat_manager.add_capability_message("email_manager", "assistant", "email_assistant", 
#                                       "I can help you send emails")
    
#     # Retrieve messages
#     current_iteration = chat_manager.get_iteration_messages("application_developer")
#     print(f"Current iteration has {len(current_iteration)} messages")
    
#     # Get latest message from an agent
#     latest_dev_message = chat_manager.get_latest_agent_message("application_developer", "dev_assistant")
#     print(f"Latest message from dev_assistant: {latest_dev_message['content']}")
    
#     # Get latest message from an agent in current iteration
#     latest_dev_iter_message = chat_manager.get_latest_iteration_agent_messages("application_developer", "dev_assistant")
#     print(f"Latest message from dev_assistant in current iteration: {latest_dev_iter_message['content']}")
    
#     # Search for messages
#     results = chat_manager.search_messages("authentication")
#     for result in results:
#         print(f"Found in {result['source']}: {result['name']} said: {result['content']}")