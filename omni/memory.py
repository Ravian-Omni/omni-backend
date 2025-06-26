from typing import Dict, List, Optional, Any, Union
from datetime import datetime
import json
from enum import Enum

class ChatType(Enum):
    MAIN = "main"
    CAPABILITY = "capability"

class MessageEntry:
    """Represents a single message entry with metadata"""
    
    def __init__(self, 
                 message: Dict[str, Any], 
                 chat_id: str,
                 chat_type: ChatType,
                 capability_name: Optional[str] = None,
                 timestamp: Optional[datetime] = None,
                 sequence_id: Optional[int] = None,
                 feedback: Optional[Dict[str, Any]] = None):
        self.message = message
        self.chat_id = chat_id
        self.chat_type = chat_type
        self.capability_name = capability_name
        self.timestamp = timestamp or datetime.now()
        self.sequence_id = sequence_id
        self.feedback = feedback or {}
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            'message': self.message,
            'chat_id': self.chat_id,
            'chat_type': self.chat_type.value,
            'capability_name': self.capability_name,
            'timestamp': self.timestamp.isoformat(),
            'sequence_id': self.sequence_id,
            'feedback': self.feedback
        }

class OmniMemory:
    """
    Memory class for PyAutoGen multi-groupchat setup with capabilities.
    Stores all messages from main chat (omni) and capability groupchats.
    """
    
    def __init__(self, main_chat_id: str = "omni"):
        self.main_chat_id = main_chat_id
        self.messages: List[MessageEntry] = []
        self.capability_instances: Dict[str, List[str]] = {}  # capability_name -> list of chat_ids
        self._sequence_counter = 0
        
    def push_message(self, 
                    message: Dict[str, Any], 
                    chat_id: str,
                    capability_name: Optional[str] = None) -> None:
        """
        Push a message to memory.
        
        Args:
            message: The message dict (standard pyautogen format)
            chat_id: Identifier for the chat/groupchat
            capability_name: Name of the capability if this is from a capability groupchat
        """
        # Determine chat type
        chat_type = ChatType.MAIN if chat_id == self.main_chat_id else ChatType.CAPABILITY
        
        # Auto-register capability instance
        if chat_type == ChatType.CAPABILITY and capability_name:
            if capability_name not in self.capability_instances:
                self.capability_instances[capability_name] = []
            if chat_id not in self.capability_instances[capability_name]:
                self.capability_instances[capability_name].append(chat_id)
        
        # Create message entry
        entry = MessageEntry(
            message=message,
            chat_id=chat_id,
            chat_type=chat_type,
            capability_name=capability_name,
            sequence_id=self._sequence_counter
        )
        
        self.messages.append(entry)
        self._sequence_counter += 1
    
    def push_main_message(self, message: Dict[str, Any]) -> None:
        """Push message to main chat (omni)"""
        self.push_message(message, self.main_chat_id)
    
    def push_capability_message(self, 
                               message: Dict[str, Any], 
                               capability_name: str,
                               chat_id: str) -> None:
        """Push message to capability chat"""
        self.push_message(message, chat_id, capability_name)
    
    def load_main_messages(self, messages: List[Dict[str, Any]]) -> None:
        """
        Load multiple messages into main chat (omni) in bulk.
        
        Args:
            messages: List of message dicts to load into main chat
        """
        for message in messages:
            self.push_main_message(message)
    
    def get_last_capability(self) -> Optional[Dict[str, str]]:
        """
        Get the last capability called.
        
        Returns:
            Dict with capability details or None if no capabilities called
            Format: {'capability_name': str, 'chat_id': str, 'timestamp': str}
        """
        # Find the last capability message
        for entry in reversed(self.messages):
            if entry.chat_type == ChatType.CAPABILITY and entry.capability_name:
                return {
                    'capability_name': entry.capability_name,
                    'chat_id': entry.chat_id,
                    'timestamp': entry.timestamp.isoformat()
                }
        return None
    
    def pull_last_capability_messages(self, include_metadata: bool = False) -> List[Union[Dict[str, Any], MessageEntry]]:
        """
        Pull all messages from the last capability called.
        
        Args:
            include_metadata: Whether to include MessageEntry objects or just message dicts
            
        Returns:
            List of messages from the last capability called, empty list if none
        """
        last_capability = self.get_last_capability()
        if not last_capability:
            return []
        
        return self.pull_capability_messages(
            capability_name=last_capability['capability_name'],
            chat_id=last_capability['chat_id'],
            include_metadata=include_metadata
        )
    
    def pull_all_messages(self, include_metadata: bool = False) -> List[Union[Dict[str, Any], MessageEntry]]:
        """Pull all messages in sequential order"""
        if include_metadata:
            return self.messages
        return [entry.message for entry in self.messages]
    
    def pull_main_messages(self, include_metadata: bool = False) -> List[Union[Dict[str, Any], MessageEntry]]:
        """Pull only main chat (omni) messages"""
        main_entries = [entry for entry in self.messages if entry.chat_type == ChatType.MAIN]
        if include_metadata:
            return main_entries
        return [entry.message for entry in main_entries]
    
    def pull_capability_messages(self, 
                                capability_name: Optional[str] = None,
                                chat_id: Optional[str] = None,
                                include_metadata: bool = False) -> List[Union[Dict[str, Any], MessageEntry]]:
        """
        Pull capability messages with optional filtering.
        
        Args:
            capability_name: Specific capability name, or None for all capabilities
            chat_id: Specific chat_id, or None for all instances of the capability
            include_metadata: Whether to include MessageEntry objects or just message dicts
        """
        capability_entries = [entry for entry in self.messages if entry.chat_type == ChatType.CAPABILITY]
        
        if capability_name:
            capability_entries = [entry for entry in capability_entries 
                                if entry.capability_name == capability_name]
        
        if chat_id:
            capability_entries = [entry for entry in capability_entries 
                                if entry.chat_id == chat_id]
            
        if include_metadata:
            return capability_entries
        return [entry.message for entry in capability_entries]
    
    def pull_recent_messages(self, 
                            count: int = 10, 
                            chat_type: Optional[str] = None,
                            capability_name: Optional[str] = None,
                            from_role: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        Pull recent messages with optional filtering.
        
        Args:
            count: Number of recent messages to return
            chat_type: Filter by chat type ('main' or 'capability')
            capability_name: Filter by specific capability name
            from_role: Filter by message role/name (e.g., 'chat_manager', 'user', 'assistant')
        """
        filtered_messages = self.messages
        
        if chat_type:
            chat_type_enum = ChatType.MAIN if chat_type == "main" else ChatType.CAPABILITY
            filtered_messages = [entry for entry in filtered_messages if entry.chat_type == chat_type_enum]
            
        if capability_name:
            filtered_messages = [entry for entry in filtered_messages 
                               if entry.capability_name == capability_name]
        
        if from_role:
            filtered_messages = [entry for entry in filtered_messages 
                               if entry.message.get('name') == from_role or entry.message.get('role') == from_role]
            
        return [entry.message for entry in filtered_messages[-count:]]
    
    def pull_recent_from_chat_manager(self, count: int = 5) -> List[Dict[str, Any]]:
        """
        Pull recent messages from chat_manager in omni chat.
        
        Args:
            count: Number of recent messages to return from chat_manager
        """
        return self.pull_recent_messages(
            count=count, 
            chat_type="main", 
            from_role="chat_manager"
        )
    
    def get_capability_instances(self, capability_name: str) -> List[str]:
        """Get all chat_ids for a specific capability"""
        return self.capability_instances.get(capability_name, [])
    
    def get_all_capabilities(self) -> Dict[str, List[str]]:
        """Get all registered capabilities and their chat_ids"""
        return self.capability_instances.copy()
    
    def add_feedback(self, 
                    sequence_id: int, 
                    feedback_type: str, 
                    feedback_value: Any,
                    feedback_notes: Optional[str] = None) -> bool:
        """
        Add feedback to a specific message.
        
        Args:
            sequence_id: Sequence ID of the message to add feedback to
            feedback_type: Type of feedback ('rating', 'helpful', 'quality', etc.)
            feedback_value: Value of the feedback (rating score, boolean, etc.)
            feedback_notes: Optional notes about the feedback
            
        Returns:
            True if feedback was added successfully, False if message not found
        """
        for entry in self.messages:
            if entry.sequence_id == sequence_id:
                entry.feedback[feedback_type] = {
                    'value': feedback_value,
                    'notes': feedback_notes,
                    'timestamp': datetime.now().isoformat()
                }
                return True
        return False
    
    def pull_messages_with_feedback(self, 
                                   feedback_type: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        Pull messages that have feedback.
        
        Args:
            feedback_type: Specific feedback type to filter by, or None for any feedback
        """
        result = []
        for entry in self.messages:
            if entry.feedback:
                if feedback_type is None or feedback_type in entry.feedback:
                    result.append({
                        'message': entry.message,
                        'sequence_id': entry.sequence_id,
                        'feedback': entry.feedback,
                        'chat_id': entry.chat_id,
                        'capability_name': entry.capability_name
                    })
        return result
    
    def get_context_for_capability(self, 
                                  capability_name: str, 
                                  chat_id: Optional[str] = None,
                                  context_length: int = 5) -> Dict[str, Any]:
        """
        Get context before a capability was called.
        
        Args:
            capability_name: Name of the capability
            chat_id: Specific chat_id, or None for latest instance
            context_length: Number of previous messages to include
        """
        # Find the capability instance
        target_entry = None
        
        if chat_id:
            # Find specific chat_id
            for entry in self.messages:
                if (entry.chat_type == ChatType.CAPABILITY and 
                    entry.capability_name == capability_name and 
                    entry.chat_id == chat_id):
                    target_entry = entry
                    break
        else:
            # Find latest instance
            for entry in reversed(self.messages):
                if (entry.chat_type == ChatType.CAPABILITY and 
                    entry.capability_name == capability_name):
                    target_entry = entry
                    break
        
        if not target_entry:
            return {'context': [], 'capability_info': None}
        
        # Get messages before this capability
        context_messages = []
        for entry in self.messages:
            if entry.sequence_id < target_entry.sequence_id:
                context_messages.append(entry.message)
        
        # Return the last context_length messages
        context_messages = context_messages[-context_length:]
        
        return {
            'context': context_messages,
            'capability_info': {
                'capability_name': target_entry.capability_name,
                'chat_id': target_entry.chat_id,
                'timestamp': target_entry.timestamp.isoformat()
            }
        }
    
    def clear_memory(self) -> None:
        """Clear all stored messages and reset counters"""
        self.messages.clear()
        self.capability_instances.clear()
        self._sequence_counter = 0
    
    def export_memory(self, filepath: str) -> None:
        """Export memory to JSON file"""
        export_data = {
            'main_chat_id': self.main_chat_id,
            'capability_instances': self.capability_instances,
            'messages': [entry.to_dict() for entry in self.messages],
            'sequence_counter': self._sequence_counter
        }
        
        with open(filepath, 'w') as f:
            json.dump(export_data, f, indent=2)
    
    def load_memory(self, filepath: str) -> None:
        """Load memory from JSON file"""
        with open(filepath, 'r') as f:
            data = json.load(f)
        
        self.main_chat_id = data['main_chat_id']
        self.capability_instances = data['capability_instances']
        self._sequence_counter = data['sequence_counter']
        
        # Reconstruct messages
        self.messages = []
        for msg_data in data['messages']:
            entry = MessageEntry(
                message=msg_data['message'],
                chat_id=msg_data['chat_id'],
                chat_type=ChatType(msg_data['chat_type']),
                capability_name=msg_data['capability_name'],
                timestamp=datetime.fromisoformat(msg_data['timestamp']),
                sequence_id=msg_data['sequence_id'],
                feedback=msg_data.get('feedback', {})
            )
            self.messages.append(entry)
    
    def get_statistics(self) -> Dict[str, Any]:
        """Get memory usage statistics"""
        main_count = len([m for m in self.messages if m.chat_type == ChatType.MAIN])
        capability_count = len([m for m in self.messages if m.chat_type == ChatType.CAPABILITY])
        
        capability_breakdown = {}
        for capability_name, chat_ids in self.capability_instances.items():
            instance_breakdown = {}
            total_messages = 0
            for chat_id in chat_ids:
                msg_count = len([m for m in self.messages if m.chat_id == chat_id])
                instance_breakdown[chat_id] = msg_count
                total_messages += msg_count
            
            capability_breakdown[capability_name] = {
                'total_messages': total_messages,
                'instances': instance_breakdown,
                'instance_count': len(chat_ids)
            }
        
        feedback_count = len([m for m in self.messages if m.feedback])
        last_capability = self.get_last_capability()
        
        return {
            'total_messages': len(self.messages),
            'main_chat_messages': main_count,
            'capability_messages': capability_count,
            'registered_capabilities': len(self.capability_instances),
            'total_capability_instances': sum(len(chat_ids) for chat_ids in self.capability_instances.values()),
            'messages_with_feedback': feedback_count,
            'last_capability_called': last_capability,
            'capability_breakdown': capability_breakdown
        }


# Comprehensive demonstration of all functions
def demonstrate_memory_usage():
    """Comprehensive demonstration of OmniMemory functionality"""
    
    print("=== PyAutoGen Memory System Demonstration ===\n")
    
    # 1. Initialize memory
    print("1. Initializing memory system...")
    memory = OmniMemory()
    print(f"   Main chat ID: {memory.main_chat_id}")
    
    # 2. Load bulk messages to main chat
    print("\n2. Loading bulk messages to main chat...")
    initial_messages = [
        {"role": "user", "content": "Hello, I need help with coding", "name": "user"},
        {"role": "assistant", "content": "I can help you with that", "name": "chat_manager"},
        {"role": "user", "content": "Great! I need Python code", "name": "user"},
        {"role": "assistant", "content": "Let me call the Python coding capability", "name": "chat_manager"}
    ]
    memory.load_main_messages(initial_messages)
    print(f"   Loaded {len(initial_messages)} messages to main chat")
    
    # 3. Push capability messages
    print("\n3. Adding capability interactions...")
    
    # Python coder capability
    memory.push_capability_message(
        {"role": "assistant", "content": "I'm ready to help with Python coding", "name": "python_coder"},
        "python_coder", "python_001"
    )
    memory.push_capability_message(
        {"role": "assistant", "content": "What specific Python task do you need?", "name": "python_coder"},
        "python_coder", "python_001"
    )
    
    # Main chat continues
    memory.push_main_message(
        {"role": "user", "content": "Actually, I also need help with emails", "name": "user"}
    )
    memory.push_main_message(
        {"role": "assistant", "content": "I'll call the email manager", "name": "chat_manager"}
    )
    
    # Email manager capability
    memory.push_capability_message(
        {"role": "assistant", "content": "Email manager ready", "name": "email_manager"},
        "email_manager", "email_001"
    )
    memory.push_capability_message(
        {"role": "assistant", "content": "I can help compose and send emails", "name": "email_manager"},
        "email_manager", "email_001"
    )
    
    # Another python coder instance
    memory.push_capability_message(
        {"role": "assistant", "content": "Another Python session started", "name": "python_coder"},
        "python_coder", "python_002"
    )
    
    print("   Added multiple capability interactions")
    
    # 4. Demonstrate last capability functions
    print("\n4. Testing last capability functions...")
    last_cap = memory.get_last_capability()
    if last_cap:
        print(f"   Last capability: {last_cap['capability_name']} (chat_id: {last_cap['chat_id']})")
        
        last_messages = memory.pull_last_capability_messages()
        print(f"   Messages from last capability: {len(last_messages)} messages")
        for msg in last_messages:
            print(f"     - {msg.get('name', 'unknown')}: {msg.get('content', '')}")
    else:
        print("   No capabilities called yet")
    
    # 5. Pull recent messages with filtering
    print("\n5. Testing message retrieval with filtering...")
    
    # Recent main chat messages
    recent_main = memory.pull_recent_messages(count=3, chat_type="main")
    print(f"   Recent main chat messages ({len(recent_main)}):")
    for msg in recent_main:
        print(f"     - {msg.get('name', 'unknown')}: {msg.get('content', '')}")
    
    # Recent from chat_manager
    chat_manager_messages = memory.pull_recent_from_chat_manager(count=2)
    print(f"   Recent chat_manager messages ({len(chat_manager_messages)}):")
    for msg in chat_manager_messages:
        print(f"     - {msg.get('name', 'unknown')}: {msg.get('content', '')}")
    
    # Recent capability messages
    recent_capabilities = memory.pull_recent_messages(count=3, chat_type="capability")
    print(f"   Recent capability messages ({len(recent_capabilities)}):")
    for msg in recent_capabilities:
        print(f"     - {msg.get('name', 'unknown')}: {msg.get('content', '')}")
    
    # 6. Demonstrate feedback system
    print("\n6. Testing feedback system...")
    
    # Add feedback to some messages
    memory.add_feedback(1, "rating", 5, "Excellent response from chat_manager")
    memory.add_feedback(4, "helpful", True, "Python coder was very helpful")
    memory.add_feedback(6, "quality", "high", "Good email manager response")
    
    print("   Added feedback to 3 messages")
    
    # Pull messages with feedback
    feedback_messages = memory.pull_messages_with_feedback()
    print(f"   Messages with feedback ({len(feedback_messages)}):")
    for msg_info in feedback_messages:
        print(f"     - Seq {msg_info['sequence_id']}: {list(msg_info['feedback'].keys())}")
    
    # Pull messages with specific feedback type
    rated_messages = memory.pull_messages_with_feedback("rating")
    print(f"   Messages with ratings ({len(rated_messages)}):")
    for msg_info in rated_messages:
        rating_info = msg_info['feedback']['rating']
        print(f"     - Rating: {rating_info['value']}/5 - {rating_info['notes']}")
    
    # 7. Capability information
    print("\n7. Capability information...")
    all_capabilities = memory.get_all_capabilities()
    print("   Registered capabilities:")
    for cap_name, chat_ids in all_capabilities.items():
        print(f"     - {cap_name}: {len(chat_ids)} instances {chat_ids}")
    
    # Get specific capability instances
    python_instances = memory.get_capability_instances("python_coder")
    print(f"   Python coder instances: {python_instances}")
    
    # 8. Context retrieval
    print("\n8. Context retrieval...")
    context = memory.get_context_for_capability("email_manager", context_length=3)
    print(f"   Context before email_manager call ({len(context['context'])} messages):")
    for msg in context['context']:
        print(f"     - {msg.get('name', 'unknown')}: {msg.get('content', '')}")
    
    # 9. Pull specific capability messages
    print("\n9. Capability-specific messages...")
    python_messages = memory.pull_capability_messages("python_coder")
    print(f"   All Python coder messages ({len(python_messages)}):")
    for msg in python_messages:
        print(f"     - {msg.get('content', '')}")
    
    python_001_messages = memory.pull_capability_messages("python_coder", "python_001")
    print(f"   Python coder instance 001 messages ({len(python_001_messages)}):")
    for msg in python_001_messages:
        print(f"     - {msg.get('content', '')}")
    
    # 10. Statistics
    print("\n10. Memory statistics...")
    stats = memory.get_statistics()
    print(f"   Total messages: {stats['total_messages']}")
    print(f"   Main chat messages: {stats['main_chat_messages']}")
    print(f"   Capability messages: {stats['capability_messages']}")
    print(f"   Messages with feedback: {stats['messages_with_feedback']}")
    print(f"   Registered capabilities: {stats['registered_capabilities']}")
    print("   Capability breakdown:")
    for cap_name, cap_info in stats['capability_breakdown'].items():
        print(f"     - {cap_name}: {cap_info['total_messages']} messages, {cap_info['instance_count']} instances")
    
    # 11. Export/Import demonstration
    print("\n11. Export/Import functionality...")
    memory.export_memory("memory_backup.json")
    print("   Memory exported to 'memory_backup.json'")
    
    # Create new memory and load
    new_memory = OmniMemory()
    new_memory.load_memory("memory_backup.json")
    print(f"   Loaded memory: {len(new_memory.messages)} messages")
    
    print("\n=== Demonstration Complete ===")
    return memory


if __name__ == "__main__":
    # Run the comprehensive demonstration
    demo_memory = demonstrate_memory_usage()